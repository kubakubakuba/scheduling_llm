import { Fragment, useEffect, useRef, useState } from 'react';

interface GanttCapacity {
    start: number;
    end: number;
    cap: number;
}

interface GanttTask {
    job: number;
    start: number;
    end: number;
    amount: number;
    y_base: number;
    is_sink: boolean;
    due_date: number | null;
    weight: number | null;
    tardiness: number | null;
    weighted_contribution: number | null;
}

interface GanttResource {
    capacity: GanttCapacity[];
    tasks: GanttTask[];
}

interface UsageResource {
    usage: number[];
    capacity: number[];
}

interface PrecedenceNode {
    id: number;
    layer?: number;
    x: number;
    y: number;
    is_sink: boolean;
}

interface PrecedenceEdge {
    from?: number;
    to?: number;
    x1: number;
    y1: number;
    x2: number;
    y2: number;
}

export interface VisualizationData {
    max_time: number;
    weighted_tardiness: number | null;
    gantt: Record<string, GanttResource>;
    usage: Record<string, UsageResource>;
    precedence: {
        max_x: number;
        max_y: number;
        edges: PrecedenceEdge[];
        nodes: PrecedenceNode[];
    };
}

export default function VisualizationDashboard({ data }: { data: VisualizationData }) {
    const safeMaxTime = data.max_time > 0 ? data.max_time : 1;
    const [activeTab, setActiveTab] = useState<'gantt' | 'usage' | 'precedence'>('gantt');
    const [hoveredTask, setHoveredTask] = useState<string | null>(null);
    const precedenceDataWidth = data.precedence.max_x || 800;
    const precedenceDataHeight = data.precedence.max_y || 600;
    const precedenceChartRef = useRef<HTMLDivElement>(null);
    const [precedenceChartWidth, setPrecedenceChartWidth] = useState(0);

    useEffect(() => {
        const element = precedenceChartRef.current;
        if (!element) return;

        const updateWidth = () => setPrecedenceChartWidth(Math.round(element.getBoundingClientRect().width));
        updateWidth();

        const observer = new ResizeObserver(updateWidth);
        observer.observe(element);
        return () => observer.disconnect();
    }, [activeTab]);

    // Fill the available panel when there is room, but retain a real canvas
    // width for narrower panels so larger graphs can be inspected by scrolling
    // instead of being compressed until their edges become hard to follow.
    const precedenceCanvasWidth = Math.max(precedenceChartWidth, Math.round(precedenceDataWidth * 1.2));
    const precedenceYScale = 1.2;
    const precedenceXScale = precedenceCanvasWidth / precedenceDataWidth;
    const precedenceYCanvasHeight = Math.max(560, Math.round(precedenceDataHeight * precedenceYScale));

    return (
        <div className="visualization-dashboard my-2 bg-[#0d0d0d] border border-zinc-800 rounded-lg overflow-hidden font-mono text-sm flex flex-col">
        <div className="flex justify-between items-center bg-[#1a1a1a] p-3 border-b border-zinc-800 shrink-0">
        <div className="flex gap-4">
        <button onClick={() => setActiveTab('gantt')} className={activeTab === 'gantt' ? 'text-zinc-200' : 'text-zinc-500 hover:text-zinc-400'}>Gantt</button>
        <button onClick={() => setActiveTab('usage')} className={activeTab === 'usage' ? 'text-zinc-200' : 'text-zinc-500 hover:text-zinc-400'}>Usage</button>
        <button onClick={() => setActiveTab('precedence')} className={activeTab === 'precedence' ? 'text-zinc-200' : 'text-zinc-500 hover:text-zinc-400'}>Precedence</button>
        </div>
        <span className="text-[#FF5722] font-semibold">Weighted Tardiness: {data.weighted_tardiness}</span>
        </div>

        <div className="p-4 flex-1 overflow-auto bg-[#0a0a0a]">
        {activeTab === 'gantt' && (
            <div className="space-y-6 inline-block min-w-full" style={{ width: `${Math.max(safeMaxTime * 20, 600)}px` }}>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[10px] text-zinc-400">
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-blue-600" />Job</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-amber-600" />Order on time</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-red-600" />Tardy order</span>
            <span className="flex items-center gap-1.5"><span className="w-4 border-t border-dashed border-fuchsia-400" />Due date</span>
            <span className="text-zinc-600">Hover over a job for details</span>
            </div>
            {Object.entries(data.gantt).map(([res, resData]) => {
                const maxAmt = Math.max(...resData.capacity.map((c) => c.cap), 1);
                const pxPerUnit = 20;
                const height = maxAmt * pxPerUnit;

                return (
                    <div key={res} className="relative">
                    <div className="text-zinc-400 mb-1">Resource {res}</div>
                    <div className="relative bg-zinc-900 border-l border-b border-zinc-700" style={{ height: height + 10 }}>
                    {resData.capacity.map((cap, i) => (
                        <div key={`cap-${i}`} className="absolute border-t-2 border-dashed border-red-500/50"
                        style={{
                            left: `${(cap.start / safeMaxTime) * 100}%`,
                                                                    width: `${((cap.end - cap.start) / safeMaxTime) * 100}%`,
                                                                    bottom: cap.cap * pxPerUnit
                        }}
                        />
                    ))}
                    {resData.tasks.map((t, i) => {
                        const isTardy = t.due_date !== null && t.end > t.due_date;
                        const taskKey = `${res}-${i}`;
                        const tooltip = [
                            `Job ${t.job}`,
                            `Start: ${t.start}`,
                            `End: ${t.end}`,
                            `Duration: ${t.end - t.start}`,
                            `Resource demand: ${t.amount}`,
                            ...(t.is_sink ? [
                                `Order due date: ${t.due_date}`,
                                `Status: ${isTardy ? 'tardy' : 'on time'}`,
                                `Tardiness: ${t.tardiness}`,
                                `Weight: ${t.weight}`,
                                `Weighted contribution: ${t.weighted_contribution}`
                            ] : [])
                        ].join('\n');

                        return (
                            <Fragment key={`task-${i}`}>
                            {t.due_date !== null && (
                                <div
                                className="pointer-events-none absolute top-0 bottom-0 z-20 border-l border-dashed border-fuchsia-400/80"
                                style={{ left: `${(t.due_date / safeMaxTime) * 100}%` }}
                                >
                                <span className="absolute top-0 left-1 rounded bg-fuchsia-950/90 px-1 py-0.5 text-[9px] text-fuchsia-200 whitespace-nowrap">
                                D={t.due_date}
                                </span>
                                </div>
                            )}
                            <div
                            className={`group absolute ${hoveredTask === taskKey ? 'z-50' : 'z-10'}`}
                            onMouseEnter={() => setHoveredTask(taskKey)}
                            onMouseLeave={() => setHoveredTask(null)}
                            style={{
                                left: `${(t.start / safeMaxTime) * 100}%`,
                                width: `${((t.end - t.start) / safeMaxTime) * 100}%`,
                                bottom: t.y_base * pxPerUnit,
                                height: t.amount * pxPerUnit
                            }}
                            >
                            <div
                            className={`relative flex h-full w-full items-center justify-center overflow-hidden rounded border border-[#0d0d0d] text-[10px] text-white ${
                                isTardy ? 'bg-red-600' : t.is_sink ? 'bg-amber-600' : 'bg-blue-600'
                            }`}
                            title={tooltip}
                            aria-label={tooltip}
                            >
                            <span className="truncate px-1">{t.job}{t.is_sink ? ' ◆' : ''}</span>
                            </div>
                            <div
                            className={`pointer-events-none absolute z-30 min-w-48 -translate-x-1/2 rounded-md border border-zinc-700 bg-zinc-950/95 p-2.5 text-[10px] leading-4 text-zinc-300 shadow-xl ${hoveredTask === taskKey ? 'block' : 'hidden'}`}
                            style={{
                                left: '50%',
                                bottom: 'calc(100% + 6px)'
                            }}
                            >
                            <div className="mb-1 font-semibold text-white">Job {t.job}{t.is_sink ? ' · Order sink' : ''}</div>
                            <div>Start: {t.start} · End: {t.end}</div>
                            <div>Duration: {t.end - t.start} · Demand: {t.amount}</div>
                            {t.is_sink && (
                                <div className="mt-1 border-t border-zinc-800 pt-1">
                                <div>Due date: <span className="text-fuchsia-300">{t.due_date}</span></div>
                                <div>Status: <span className={isTardy ? 'text-red-300' : 'text-emerald-300'}>{isTardy ? 'Tardy' : 'On time'}</span></div>
                                <div>Tardiness: {t.tardiness} · Weight: {t.weight}</div>
                                <div>Objective contribution: {t.weighted_contribution}</div>
                                </div>
                            )}
                            </div>
                            </div>
                            </Fragment>
                        );
                    })}
                    </div>
                    </div>
                );
            })}

            <div className="relative mt-4 border-t border-zinc-700 h-6 text-zinc-500 text-[10px]">
            {Array.from({ length: Math.ceil(safeMaxTime / 10) + 1 }).map((_, i) => (
                <div key={i} className="absolute border-l border-zinc-700 pl-1 h-full" style={{ left: `${((i * 10) / safeMaxTime) * 100}%` }}>
                {i * 10}
                </div>
            ))}
            </div>
            </div>
        )}

        {activeTab === 'usage' && (
            <div className="space-y-8 w-full min-w-0">
            {Object.entries(data.usage).map(([res, resData]) => {
                const maxVal = Math.max(...resData.capacity, ...resData.usage, 1);
                const height = 120;

                let usagePath = `M 0 ${height}`;
                for (let i = 0; i < safeMaxTime; i++) {
                    const val = resData.usage[i] || 0;
                    const y = height - (val / maxVal) * height;
                    usagePath += ` L ${i} ${y} L ${i + 1} ${y}`;
                }
                usagePath += ` L ${safeMaxTime} ${height} Z`;

                let capPath = `M 0 ${height - ((resData.capacity[0] || 0) / maxVal) * height}`;
                for (let i = 0; i < safeMaxTime; i++) {
                    const val = resData.capacity[i] || 0;
                    const y = height - (val / maxVal) * height;
                    capPath += ` L ${i} ${y} L ${i + 1} ${y}`;
                }

                return (
                    <div key={res} className="flex gap-4">
                    <div className="flex flex-col justify-between items-end text-zinc-500 pb-5 shrink-0 w-8" style={{ height: height + 20 }}>
                    <span>{maxVal}</span>
                    <span>{Math.round(maxVal / 2)}</span>
                    <span>0</span>
                    </div>
                    <div className="min-w-0 flex-1">
                    <div className="text-zinc-400 mb-1">Resource {res} Usage</div>
                    <svg viewBox={`0 0 ${safeMaxTime} ${height}`} preserveAspectRatio="none" width="100%" height={height} className="bg-zinc-900 border-l border-b border-zinc-700 block overflow-visible">
                    <path d={usagePath} fill="rgba(59, 130, 246, 0.3)" stroke="#3b82f6" strokeWidth="1" vectorEffect="non-scaling-stroke" />
                    <path d={capPath} fill="none" stroke="#ef4444" strokeWidth="1.5" strokeDasharray="4 2" vectorEffect="non-scaling-stroke" />
                    </svg>
                    <div className="relative mt-1 w-full text-zinc-500">
                    {[0, Math.floor(safeMaxTime / 2), safeMaxTime].map((t) => (
                        <div key={t} className="absolute" style={{ left: `${(t / safeMaxTime) * 100}%`, transform: t === 0 ? undefined : t === safeMaxTime ? 'translateX(-100%)' : 'translateX(-50%)' }}>
                        {t}
                        </div>
                    ))}
                    </div>
                    </div>
                    </div>
                );
            })}
            </div>
        )}

        {activeTab === 'precedence' && (
            <div ref={precedenceChartRef} className="w-full min-w-0 min-h-full">
            <svg
          viewBox={`0 0 ${precedenceCanvasWidth} ${precedenceYCanvasHeight}`}
          width={precedenceCanvasWidth}
          height={precedenceYCanvasHeight}
          preserveAspectRatio="none"
          className="precedence-chart bg-[#0a0a0a] block"
            >
            {data.precedence.edges.map((e, i) => (
                <line key={i} x1={e.x1 * precedenceXScale} y1={e.y1 * precedenceYScale} x2={e.x2 * precedenceXScale} y2={e.y2 * precedenceYScale} stroke="#52525b" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
            ))}
            {data.precedence.nodes.map((n) => (
                <g key={n.id} transform={`translate(${n.x * precedenceXScale}, ${n.y * precedenceYScale})`}>
                <circle r="20" fill={n.is_sink ? "#ea580c" : "#2563eb"} stroke="#18181b" strokeWidth="2" />
                <text textAnchor="middle" dy=".3em" fill="white" fontSize="15" fontWeight="bold">
                {n.id}
                </text>
                </g>
            ))}
            </svg>
            </div>
        )}
        </div>
        </div>
    );
}
