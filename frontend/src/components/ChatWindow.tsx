import { Component, Fragment, useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import type { ChatMessage, ConfigStatus, ToolCall } from '../types';
import VisualizationDashboard, { type VisualizationData } from './VisualizationDashboard';

interface ChatWindowProps {
    messages: ChatMessage[];
    onSendMessage: (message: string) => void;
    onFileUpload: (file: File) => void;
    isLoading: boolean;
    isStopping: boolean;
    generationStatus: { stage: string; elapsedSeconds: number };
    onStop: () => void;
    onOpenSource?: (toolCall: ToolCall) => void;
    onNewChat?: () => void;
    instanceName?: string | null;
    configStatus: ConfigStatus;
}

type ToolPayload = {
    status?: string;
    error_code?: string;
    visualization_type?: string;
    message?: string;
    error?: string;
    weighted_tardiness?: number | null;
    max_time?: number;
    objective?: number | null;
    data?: unknown;
    gantt?: Record<string, unknown>;
    validation_errors?: Array<{ path?: string; message?: string }>;
    artifact_id?: string;
    title?: string;
    [key: string]: unknown;
};

function Icon({ name, size = 18 }: { name: 'paperclip' | 'arrow' | 'copy' | 'check' | 'wrench' | 'stop'; size?: number }) {
    const common = {
        width: size,
        height: size,
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.8,
        strokeLinecap: 'round' as const,
        strokeLinejoin: 'round' as const,
    };

    if (name === 'paperclip') return <svg {...common}><path d="m21.4 11.6-8.8 8.8a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" /></svg>;
    if (name === 'arrow') return <svg {...common}><path d="M5 12h13" /><path d="m13 6 6 6-6 6" /></svg>;
    if (name === 'copy') return <svg {...common}><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg>;
    if (name === 'check') return <svg {...common}><path d="m5 12 4 4L19 6" /></svg>;
    if (name === 'stop') return <svg {...common} fill="currentColor" stroke="none"><rect x="6" y="6" width="12" height="12" rx="1.5" /></svg>;
    // Heroicons WrenchScrewdriverIcon (24px outline), used for tool calls.
    return <svg {...common} strokeWidth={1.5}><path d="M11.42 15.17 17.25 21A2.652 2.652 0 0 0 21 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 1 1-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 0 0 4.486-6.336l-3.276 3.277a3.004 3.004 0 0 1-2.25-2.25l3.276-3.276a4.5 4.5 0 0 0-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437 1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008Z" /></svg>;
}

function readToolPayload(content: string): ToolPayload | null {
    try {
        const parsed: unknown = JSON.parse(content);
        return parsed && typeof parsed === 'object' ? parsed as ToolPayload : null;
    } catch {
        return null;
    }
}

function formatJson(value: unknown) {
    if (typeof value === 'string') return value;
    try {
        return JSON.stringify(value, null, 2) ?? String(value);
    } catch {
        return String(value);
    }
}

function compactSourceFields(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(compactSourceFields);
    if (!value || typeof value !== 'object') return value;
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => {
        if ((key === 'source' || key === 'solver_source') && typeof item === 'string' && item.length > 400) {
            return [key, `[${item.length.toLocaleString()} characters; open the source in Code workspace]`];
        }
        return [key, compactSourceFields(item)];
    }));
}

function parseArguments(rawArguments: string) {
    try {
        return { valid: true, value: JSON.parse(rawArguments) as unknown };
    } catch {
        return { valid: false, value: rawArguments || '(empty)' };
    }
}

function toolStatus(payload: ToolPayload | null, pending: boolean) {
    if (pending) return { label: 'Running', className: 'tool-status-neutral' };

    if (payload?.error_code === 'invalid_tool_arguments') {
        return { label: 'Rejected', className: 'tool-status-error' };
    }

    const status = payload?.status || payload?.error_code || 'output';
    if (['success', 'optimal', 'feasible', 'committed'].includes(status)) {
        return { label: status === 'success' ? 'Complete' : status, className: 'tool-status-success' };
    }
    if (['rejected', 'infeasible'].includes(status)) {
        return { label: status.replace(/_/g, ' '), className: 'tool-status-warning' };
    }
    if (['error', 'invalid_instance', 'solver_error', 'tool_execution_failed', 'invalid_tool_arguments', 'unknown_tool'].includes(status)) {
        return { label: status.replace(/_/g, ' '), className: 'tool-status-error' };
    }
    return { label: status.replace(/_/g, ' '), className: 'tool-status-neutral' };
}

function toolSummary(payload: ToolPayload | null, functionName: string, pending: boolean) {
    if (pending) return 'Waiting for the tool to return a result…';
    if (!payload) return 'The tool returned an unreadable result.';
    if (typeof payload.message === 'string' && payload.message) return payload.message;
    if (typeof payload.error === 'string' && payload.error) return payload.error;
    if (payload.visualization_type === 'full_dashboard') {
        return `Schedule visualization generated${payload.weighted_tardiness === null || payload.weighted_tardiness === undefined ? '' : ` with weighted tardiness ${payload.weighted_tardiness}`}.`;
    }
    if (payload.objective !== undefined && payload.objective !== null) {
        return `${functionName} returned objective ${payload.objective}.`;
    }
    if (payload.data && typeof payload.data === 'object') {
        return `${functionName} returned ${Object.keys(payload.data).length} value${Object.keys(payload.data).length === 1 ? '' : 's'}.`;
    }
    return `${functionName} completed with status ${payload.status || 'unknown'}.`;
}

function compactVisualizationOutput(payload: ToolPayload) {
    return formatJson({
        status: payload.status,
        visualization_type: payload.visualization_type,
        weighted_tardiness: payload.weighted_tardiness,
        max_time: payload.max_time,
        resources: payload.gantt ? Object.keys(payload.gantt) : undefined,
        message: payload.message,
    });
}

function isFailedTool(payload: ToolPayload | null) {
    return Boolean(payload?.error_code) || ['error', 'rejected', 'infeasible', 'solver_error'].includes(payload?.status || '');
}

function AnalysisVisualizations({ payload }: { payload: ToolPayload | null }) {
    const charts = payload?.visualizations;
    if (!Array.isArray(charts)) return null;
    return <div className="analysis-visualizations">{charts.map((chart, index) => {
        if (!chart || typeof chart !== 'object') return null;
        const value = chart as { title?: string; type?: string; kind?: string; labels?: unknown[]; values?: unknown[]; spec?: { data?: unknown[] }; option?: { xAxis?: { data?: unknown[] }; series?: unknown[] }; elements?: unknown };
        if (value.kind === 'plotly' || value.kind === 'echarts' || value.kind === 'cytoscape') return <DeclarativeVisualization key={index} chart={value} />;
        if (value.type !== 'bar' || !Array.isArray(value.labels) || !Array.isArray(value.values)) return null;
        const values = value.values.map((item) => typeof item === 'number' ? item : 0);
        const max = Math.max(...values, 1);
        return <div className="analysis-chart" key={index}><div className="analysis-chart-title">{value.title || 'Analysis'}</div>{value.labels.map((label, itemIndex) => <div className="analysis-bar-row" key={itemIndex}><span>{String(label)}</span><div className="analysis-bar-track"><div className="analysis-bar" style={{ width: `${Math.max(0, values[itemIndex] || 0) / max * 100}%` }} /></div><b>{values[itemIndex] ?? 0}</b></div>)}</div>;
    })}</div>;
}

function DeclarativeVisualization({ chart }: { chart: { title?: string; kind?: string; spec?: { data?: unknown[] }; option?: { xAxis?: { data?: unknown[] }; series?: unknown[] }; elements?: unknown } }) {
    const traces = chart.kind === 'plotly' && Array.isArray(chart.spec?.data)
        ? chart.spec.data.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
        : chart.kind === 'echarts' && Array.isArray(chart.option?.series)
            ? chart.option.series.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
            : [];
    if (chart.kind === 'cytoscape') {
        const raw = Array.isArray(chart.elements) ? chart.elements : [];
        const nodes = raw.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && (item as Record<string, unknown>).data && typeof (item as Record<string, unknown>).data === 'object' && !((item as Record<string, unknown>).data as Record<string, unknown>).source));
        const edges = raw.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && (item as Record<string, unknown>).data && typeof (item as Record<string, unknown>).data === 'object' && ((item as Record<string, unknown>).data as Record<string, unknown>).source));
        const positions = new Map(nodes.map((node, index) => [String((node.data as Record<string, unknown>).id), { x: 60 + (index % 6) * 110, y: 60 + Math.floor(index / 6) * 75 }]));
        return <div className="analysis-chart"><div className="analysis-chart-title">{chart.title || 'Network graph'}</div><svg className="analysis-network" viewBox="0 0 720 300" role="img" aria-label={chart.title || 'Network graph'}>{edges.map((edge, index) => { const data = edge.data as Record<string, unknown>; const from = positions.get(String(data.source)); const to = positions.get(String(data.target)); return from && to ? <line key={index} x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="#71717a" strokeWidth="2" /> : null; })}{nodes.map((node, index) => { const data = node.data as Record<string, unknown>; const position = positions.get(String(data.id))!; return <g key={index}><circle cx={position.x} cy={position.y} r="20" fill="#2563eb" /><text x={position.x} y={position.y + 4} textAnchor="middle" fill="white" fontSize="10">{String(data.label ?? data.id)}</text></g>; })}</svg></div>;
    }
    const labels = chart.kind === 'echarts' ? (chart.option?.xAxis?.data || []) : [];
    const first = traces[0] || {};
    const values = Array.isArray(first.y) ? first.y : Array.isArray(first.data) ? first.data : [];
    const numbers = values.map((item) => typeof item === 'number' ? item : 0);
    const max = Math.max(...numbers.map(Math.abs), 1);
    const isBar = first.type === 'bar' || chart.kind === 'echarts' && first.type !== 'line';
    return <div className="analysis-chart"><div className="analysis-chart-title">{chart.title || String(first.name || 'Chart')}</div><svg className="analysis-spec-chart" viewBox="0 0 720 260" role="img" aria-label={chart.title || 'Chart'}>{numbers.map((number, index) => { const x = 30 + index * Math.max(12, 680 / Math.max(numbers.length, 1)); const y = 220 - (number / max) * 180; return isBar ? <rect key={index} x={x} y={Math.min(y, 220)} width={Math.max(5, 600 / Math.max(numbers.length, 1))} height={Math.abs(220 - y)} fill="#fb923c"><title>{`${labels[index] ?? index}: ${number}`}</title></rect> : <circle key={index} cx={x} cy={y} r="4" fill="#60a5fa"><title>{`${labels[index] ?? index}: ${number}`}</title></circle>; })}</svg></div>;
}

function VisualizationApplet({ artifactId, conversationId, title }: { artifactId: string; conversationId?: string | null; title?: string }) {
    const [height, setHeight] = useState(420);
    const [error, setError] = useState<string | null>(null);
    const [reloadKey, setReloadKey] = useState(0);
    const frameRef = useRef<HTMLIFrameElement>(null);
    const apiBase = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

    useEffect(() => {
        const handleMessage = (event: MessageEvent) => {
            if (event.source !== frameRef.current?.contentWindow || !event.data || typeof event.data !== 'object') return;
            if (event.data.type === 'scheduling-applet-size' && Number.isFinite(event.data.height)) {
                setHeight(Math.max(180, Math.min(1600, Number(event.data.height))));
            }
            if (event.data.type === 'scheduling-applet-error') setError(String(event.data.message || 'The visualization failed to render.'));
        };
        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, []);

    if (!conversationId) return <div className="analysis-applet-error">The visualization is unavailable because its conversation is not loaded.</div>;
    const frameUrl = `${apiBase}/api/conversations/${encodeURIComponent(conversationId)}/artifacts/${encodeURIComponent(artifactId)}/frame`;
    const retry = () => { setError(null); setReloadKey((value) => value + 1); };
    const fullscreen = () => { void frameRef.current?.requestFullscreen?.(); };
    return <div className="analysis-applet">
        <div className="analysis-applet-header"><div className="analysis-chart-title">{title || 'Custom visualization'}</div><div className="analysis-applet-actions"><button type="button" onClick={retry}>Retry</button><button type="button" onClick={fullscreen}>Fullscreen</button></div></div>
        {error && <div className="analysis-applet-error">{error}</div>}
        <iframe key={reloadKey} ref={frameRef} title={title || 'Custom visualization'} src={frameUrl} sandbox="allow-scripts" allowFullScreen style={{ height }} />
    </div>;
}

function ToolExecutionCard({ toolCall, result, isLoading, onOpenSource, conversationId }: { toolCall: ToolCall; result?: ChatMessage; isLoading: boolean; onOpenSource?: (toolCall: ToolCall) => void; conversationId?: string | null }) {
    const payload = result ? readToolPayload(result.content) : null;
    const pending = !result;
    const status = toolStatus(payload, pending);
    const argumentsValue = parseArguments(toolCall.function.arguments);
    const inputText = formatJson(compactSourceFields(argumentsValue.value));
    const outputText = pending
        ? 'Waiting for the tool output…'
        : payload?.visualization_type === 'full_dashboard'
            ? compactVisualizationOutput(payload)
            : result
                ? formatJson(compactSourceFields(payload || result.content))
                : 'No output returned.';

    return (
        <section className={`tool-execution ${pending ? 'tool-execution-pending' : ''}`}>
            <div className="tool-execution-header">
                <div className="tool-execution-name">
                    <span className={`tool-call-icon ${pending && isLoading ? 'tool-call-icon-active' : ''}`}><Icon name="wrench" size={15} /></span>
                    <code>{toolCall.function.name}</code>
                </div>
                <div className="tool-execution-header-actions">{onOpenSource && ['get_solver_source', 'write_solver_variant', 'write_analysis_script', 'write_visualization_applet'].includes(toolCall.function.name) && <button className="tool-source-button" onClick={() => onOpenSource(toolCall)}>Open source</button>}<span className={`tool-status ${status.className}`}>{status.label}</span></div>
            </div>
            <p className="tool-execution-summary">{toolSummary(payload, toolCall.function.name, pending)}</p>
            <details className="tool-execution-details" open={!pending && isFailedTool(payload)}>
                <summary>View input and output <span className="summary-chevron">⌄</span></summary>
                <div className="tool-execution-section">
                    <div className="tool-execution-section-title">
                        <span>Input</span>
                        {!argumentsValue.valid && <span className="tool-input-warning">Invalid JSON</span>}
                    </div>
                    <pre>{inputText}</pre>
                </div>
                <div className="tool-execution-section">
                    <div className="tool-execution-section-title">Output</div>
                    <pre>{outputText}</pre>
                    <AnalysisVisualizations payload={payload} />
                </div>
            </details>
            {payload?.visualization_type === 'custom_applet' && payload.artifact_id && <VisualizationApplet artifactId={payload.artifact_id} conversationId={conversationId} title={payload.title} />}
        </section>
    );
}

function readVisualizationData(result?: ChatMessage): VisualizationData | null {
    if (!result || readToolPayload(result.content)?.visualization_type !== 'full_dashboard') return null;
    try {
        const parsed: unknown = JSON.parse(result.content);
        if (!parsed || typeof parsed !== 'object') return null;
        const value = parsed as Record<string, unknown>;
        const precedence = value.precedence;
        if (typeof value.max_time !== 'number' || !value.gantt || typeof value.gantt !== 'object' || !value.usage || typeof value.usage !== 'object' || !precedence || typeof precedence !== 'object') return null;
        const graph = precedence as Record<string, unknown>;
        if (typeof graph.max_x !== 'number' || typeof graph.max_y !== 'number' || !Array.isArray(graph.edges) || !Array.isArray(graph.nodes)) return null;
        return value as unknown as VisualizationData;
    } catch {
        return null;
    }
}

class VisualizationErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
    state = { failed: false };

    static getDerivedStateFromError() {
        return { failed: true };
    }

    render() {
        if (this.state.failed) return <div className="analysis-applet-error">This archived schedule visualization could not be rendered. The tool result is preserved and can be inspected or deleted from the conversation sidebar.</div>;
        return this.props.children;
    }
}

export default function ChatWindow({ messages, onSendMessage, onFileUpload, isLoading, isStopping, generationStatus, onStop, onOpenSource, onNewChat, instanceName, configStatus, conversationId }: ChatWindowProps & { conversationId?: string | null }) {
    const [input, setInput] = useState('');
    const [copiedMessage, setCopiedMessage] = useState<number | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        if (!textareaRef.current) return;
        textareaRef.current.style.height = 'auto';
        textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }, [input]);

    const handleSend = () => {
        const message = input.trim();
        if (!message || isLoading) return;
        onSendMessage(message);
        setInput('');
    };

    const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            handleSend();
        }
    };

    const handleFileSelect = (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (file) onFileUpload(file);
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    const copyMessage = async (index: number, content: string) => {
        try {
            await navigator.clipboard.writeText(content);
            setCopiedMessage(index);
            window.setTimeout(() => setCopiedMessage((current) => current === index ? null : current), 1600);
        } catch {
            // Clipboard access can be unavailable outside a secure browser context.
        }
    };

    const formatContent = (text: string) => text.replace(/<([a-zA-Z0-9_]+)>([\s\S]*?)<\/\1>/g, '\n\n> **[$1]** `$2`\n\n');
    const canChat = configStatus.state === 'ready';
    const quickActions = [
        { label: 'Solve', prompt: 'Solve the current instance and summarize the result.' },
        { label: 'Explain', prompt: 'Explain the current instance, its structure, constraints, and likely bottlenecks.' },
        { label: 'Visualize', prompt: 'Solve the current instance if necessary, then visualize the resulting schedule.' },
    ];
    const toolResultsById = new Map(
        messages
            .filter((message) => message.role === 'tool' && message.tool_call_id)
            .map((message) => [message.tool_call_id as string, message]),
    );
    const knownToolCallIds = new Set(
        messages.flatMap((message) => message.tool_calls?.map((toolCall) => toolCall.id) || []),
    );

    return (
        <main className="chat-window">
            <div className="chat-scroll-area">
                {messages.length === 0 ? (
                    <div className="empty-state">
                        <p className="empty-state-title">No instance loaded</p>
                        <p>Upload a JSON scheduling instance using the paperclip below.</p>
                        <p>Once it is loaded, you can ask questions or use the quick actions.</p>
                        {configStatus.state === 'error' && <p className="empty-state-error">{configStatus.message}</p>}
                    </div>
                ) : (
                    <div className="message-list">
                        {messages.map((message, index) => {
                            if (message.role === 'system') return null;

                            if (message.role === 'tool') {
                                if (message.tool_call_id && knownToolCallIds.has(message.tool_call_id)) return null;
                                const fallbackToolCall: ToolCall = {
                                    id: message.tool_call_id || `unmatched-${index}`,
                                    type: 'function',
                                    function: { name: message.name || 'Tool result', arguments: '{}' },
                                };
                                return (
                                <div key={index} className="tool-message-group">
                                    <ToolExecutionCard toolCall={fallbackToolCall} result={message} isLoading={isLoading} onOpenSource={onOpenSource} conversationId={conversationId} />
                                    </div>
                                );
                            }

                            if (message.role === 'assistant' && message.tool_calls?.length) {
                                return (
                                    <div key={index} className="tool-message-group">
                                        {message.content && (
                                            <div className="message-markdown tool-message-text">
                                                <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>{formatContent(message.content)}</ReactMarkdown>
                                            </div>
                                        )}
                                        {message.tool_calls.map((toolCall) => {
                                            const result = toolResultsById.get(toolCall.id);
                                            const visualizationData = readVisualizationData(result);
                                            return (
                                                <Fragment key={toolCall.id}>
                                                    <ToolExecutionCard toolCall={toolCall} result={result} isLoading={isLoading} onOpenSource={onOpenSource} conversationId={conversationId} />
                                                    {visualizationData && (
                                                        <div className="dashboard-message">
                                                            <VisualizationErrorBoundary><VisualizationDashboard data={visualizationData} /></VisualizationErrorBoundary>
                                                        </div>
                                                    )}
                                                </Fragment>
                                            );
                                        })}
                                    </div>
                                );
                            }

                            const isUser = message.role === 'user';

                            return (
                                <article key={index} className={`message-row ${isUser ? 'message-row-user' : ''}`}>
                                    {!isUser && <div className="message-avatar"><span className="message-avatar-label">AI</span></div>}
                                    <div className={`message-content ${isUser ? 'message-content-user' : ''}`}>
                                        {!isUser && (
                                            <div className="message-meta">
                                                <span>Thesis LLM</span>
                                            </div>
                                        )}

                                        {message.reasoning && (
                                            <details className="reasoning-block">
                                                <summary>View reasoning trace</summary>
                                                <div>{message.reasoning}</div>
                                            </details>
                                        )}
                                        {message.content && (
                                            <div className={`message-markdown ${isUser ? 'message-markdown-user' : ''}`}>
                                                {isUser ? <p>{message.content}</p> : <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>{formatContent(message.content)}</ReactMarkdown>}
                                            </div>
                                        )}
                                        {!isUser && message.content && (
                                            <button className="copy-message-button" onClick={() => copyMessage(index, message.content)}>
                                                <Icon name={copiedMessage === index ? 'check' : 'copy'} size={13} />
                                                {copiedMessage === index ? 'Copied' : 'Copy'}
                                            </button>
                                        )}
                                    </div>
                                </article>
                            );
                        })}
                        {isLoading && (
                            <div className="message-row">
                                <div className="message-avatar"><span className="message-avatar-label">AI</span></div>
                                <div className="loading-message"><span className="loading-dots"><i /><i /><i /></span> {isStopping ? 'Stopping…' : `${generationStatus.stage === 'running tool' ? 'Running a tool' : generationStatus.stage === 'finalizing' ? 'Finalizing' : 'Thinking'}${generationStatus.elapsedSeconds > 0 ? ` · ${Math.floor(generationStatus.elapsedSeconds / 60)}m ${Math.floor(generationStatus.elapsedSeconds % 60)}s` : ''}`}</div>
                            </div>
                        )}
                    </div>
                )}
            </div>

            <div className="composer-wrap">
                {instanceName && (
                    <div className="quick-actions" aria-label="Quick actions">
                        <span className="quick-actions-label">Quick actions</span>
                        <div className="quick-actions-list">
                            {quickActions.map((action) => (
                                <button
                                    key={action.label}
                                    className="quick-action"
                                    onClick={() => onSendMessage(action.prompt)}
                                    disabled={isLoading || !canChat}
                                    title={!canChat ? configStatus.message : action.prompt}
                                >
                                    {action.label}
                                </button>
                            ))}
                        </div>
                    </div>
                )}
                <div className="composer">
                    <input type="file" accept=".json,application/json" ref={fileInputRef} onChange={handleFileSelect} className="hidden" />
                    <button className="composer-icon-button" onClick={() => fileInputRef.current?.click()} disabled={isLoading} title="Upload JSON instance" aria-label="Upload JSON instance">
                        <Icon name="paperclip" size={18} />
                    </button>
                    <textarea
                        ref={textareaRef}
                        value={input}
                        onChange={(event) => setInput(event.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder={configStatus.state === 'loading' ? 'Preparing the model connection…' : configStatus.state === 'error' ? 'Configure the model connection to continue…' : instanceName ? 'Ask about your schedule…' : 'Upload an instance to begin…'}
                        rows={1}
                        aria-label="Message"
                        disabled={isLoading || !canChat}
                    />
                    <button className={`send-button ${isLoading ? 'send-button-stop' : ''}`} onClick={isLoading ? onStop : handleSend} disabled={isLoading ? isStopping : (!input.trim() || !canChat)} aria-label={isLoading ? 'Stop generation' : 'Send message'} title={isLoading ? 'Stop generation' : (configStatus.message ?? 'Send message')}>
                        <Icon name={isLoading ? 'stop' : 'arrow'} size={17} />
                    </button>
                </div>
                <div className="composer-footer">
                    <span><kbd>Enter</kbd> to send <span className="hidden sm:inline">· <kbd>Shift</kbd> + <kbd>Enter</kbd> for a new line</span></span>
                    {onNewChat && messages.length > 0 && <button onClick={onNewChat} disabled={isLoading}>Clear conversation</button>}
                </div>
            </div>
        </main>
    );
}
