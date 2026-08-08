import { useState, useRef, type KeyboardEvent, type ChangeEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import type { ChatMessage } from '../types';
import VisualizationDashboard from './VisualizationDashboard';

interface ChatWindowProps {
    messages: ChatMessage[];
    onSendMessage: (message: string) => void;
    onFileUpload: (file: File) => void;
    isLoading: boolean;
}

export default function ChatWindow({ messages, onSendMessage, onFileUpload, isLoading }: ChatWindowProps) {
    const [input, setInput] = useState('');
    const fileInputRef = useRef<HTMLInputElement>(null);

    const handleSend = () => {
        if (!input.trim() || isLoading) return;
        onSendMessage(input);
        setInput('');
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const handleFileSelect = (e: ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            onFileUpload(file);
        }
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    const formatContent = (text: string) => {
        if (!text) return '';
        return text.replace(/<([a-zA-Z0-9_]+)>([\s\S]*?)<\/\1>/g, '\n\n> **[$1]** `$2`\n\n');
    };

    return (
        <main className="flex-1 flex flex-col h-full bg-[#121212] overflow-hidden">
        <div className="flex-1 overflow-y-auto py-6 flex flex-col">
        {messages.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
            <h3 className="text-sm font-medium text-zinc-300 mb-2 tracking-wide">Workspace Ready</h3>
            <p className="text-xs text-zinc-500 max-w-sm">
            Use the paperclip icon to upload an MRCPSP instance, or begin typing to interact with the solver.
            </p>
            </div>
        ) : (
            <div className="w-full space-y-6 pb-4 flex flex-col items-center">
            {messages.map((msg, idx) => {
                if (msg.role === 'system') return null;
                const isUser = msg.role === 'user';
                const isTool = msg.role === 'tool';

            const isDashboard = isTool && (() => {
                try { return JSON.parse(msg.content).visualization_type === 'full_dashboard'; }
                catch { return false; }
            })();

            return (
                <div key={idx} className="w-full flex justify-center px-4">
                <div className={`flex flex-col w-full ${isDashboard ? 'max-w-[95vw] items-center' : 'max-w-3xl ' + (isUser ? 'items-end' : 'items-start')}`}>
                <div className={`rounded-lg px-4 py-3 text-sm leading-relaxed ${
                    isDashboard ? 'w-auto max-w-full bg-transparent p-0' :
                    isUser ? 'bg-zinc-800 text-zinc-100 max-w-full' :
                    isTool ? 'bg-zinc-900 border border-zinc-800/50 w-full' :
                    'bg-[#181818] border border-zinc-800 text-zinc-300 w-full'
                }`}>

                {isTool && (() => {
                    if (isDashboard) {
                        return <VisualizationDashboard data={JSON.parse(msg.content)} />;
                    }

                    return (
                        <details className="group">
                        <summary className="text-xs text-zinc-400 cursor-pointer select-none hover:text-zinc-200 flex items-center gap-2">
                        <svg className="w-4 h-4 text-[#FF5722]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                        </svg>
                        Result from <strong>{msg.name || 'tool'}</strong>
                        </summary>
                        <div className="mt-3 bg-[#0a0a0a] p-3 rounded border border-zinc-800 overflow-x-auto">
                        <pre className="text-[11px] text-zinc-400 font-mono m-0">
                        {msg.content}
                        </pre>
                        </div>
                        </details>
                    );
                })()}

                {!isUser && !isTool && msg.tool_calls && msg.tool_calls.map((tc, i) => {
                    const isActivelyExecuting = isLoading && idx === messages.length - 1;

                    return (
                        <div key={i} className="mb-3 inline-flex items-center gap-2 bg-zinc-900 border border-zinc-700 px-3 py-1.5 rounded-full text-xs text-zinc-300 font-mono transition-colors">
                        <span className={`w-2 h-2 rounded-full transition-colors ${
                            isActivelyExecuting ? 'bg-[#FF5722] animate-pulse' : 'bg-zinc-600'
                        }`} />
                        {isActivelyExecuting ? 'Executing:' : 'Executed:'} {tc.function.name}
                        </div>
                    );
                })}

                {!isUser && !isTool && msg.reasoning && (
                    <details className="mb-3 group">
                    <summary className="text-xs text-zinc-500 cursor-pointer select-none hover:text-zinc-300 transition-colors">
                    Thought Process
                    </summary>
                    <div className="mt-2 pl-3 border-l-2 border-zinc-700 text-xs text-zinc-400 font-mono whitespace-pre-wrap">
                    {msg.reasoning}
                    </div>
                    </details>
                )}

                {!isTool && msg.content && (
                    <div className="prose prose-invert prose-sm max-w-none">
                    {isUser ? (
                        <div className="whitespace-pre-wrap font-sans">{msg.content}</div>
                    ) : (
                        <ReactMarkdown
                        remarkPlugins={[remarkGfm, remarkMath]}
                        rehypePlugins={[rehypeKatex]}
                        >
                        {formatContent(msg.content)}
                        </ReactMarkdown>
                    )}
                    </div>
                )}
                </div>
                </div>
                </div>
            );
            })}
            {isLoading && (
                <div className="flex items-center gap-2 text-xs font-mono text-zinc-500 w-full max-w-3xl">
                <span className="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-pulse" />
                Processing
                </div>
            )}
            </div>
        )}
        </div>

        <div className="p-4 bg-[#121212] shrink-0">
        <div className="max-w-4xl mx-auto flex items-end gap-2 bg-[#1a1a1a] border border-zinc-800 rounded-md p-2 focus-within:border-zinc-500 transition-colors">

        <input
        type="file"
        accept=".json"
        ref={fileInputRef}
        onChange={handleFileSelect}
        className="hidden"
        />

        <button
        onClick={() => fileInputRef.current?.click()}
        className="p-2 text-zinc-400 hover:text-zinc-200 transition-colors shrink-0"
        title="Upload JSON Instance"
        >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
        </svg>
        </button>

        <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Send a message..."
        rows={1}
        className="flex-1 bg-transparent border-none text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none resize-none p-2 min-h-[40px]"
        />

        <button
        onClick={handleSend}
        disabled={!input.trim() || isLoading}
        className="p-2 text-zinc-400 hover:text-zinc-200 disabled:opacity-50 transition-colors shrink-0"
        >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
        </svg>
        </button>
        </div>
        </div>
        </main>
    );
}
