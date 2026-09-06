export interface Settings {
    provider: string;
    endpointUri: string;
    modelName: string;
    systemPrompt: string;
    requestTimeoutSeconds: number;
    maxToolRounds: number;
    sandboxTimeoutSeconds: number;
}

export interface MRCPSPInstance {
    instance_name: string;
    jobs: number[];
    durations: Record<string, number>;
    predecessors: Record<string, number[]>;
    resources: string[];
    requests: Array<{
        job: number;
        resource: string;
        amount: number;
    }>;
    shifts: Record<string, Array<[number, number, number]>>;
    orders: Array<{
        sink_job: number;
        due_date: number;
        weight: number;
    }>;
}

export interface ToolCall {
    id: string;
    type: string;
    function: {
        name: string;
        arguments: string;
    };
}

export interface ChatMessage {
    role: 'user' | 'assistant' | 'system' | 'tool';
    content: string;
    reasoning?: string | null;
    tool_calls?: ToolCall[];
    tool_call_id?: string;
    name?: string;
    incomplete?: boolean;
    status?: string;
    generation_id?: string;
    created_at?: string;
    sequence?: number;
    library_references?: LibraryReference[];
}

export interface LibraryReference {
    kind: 'analysis' | 'visualization';
    id: string;
    name: string;
    description?: string;
    status?: string;
    origin?: 'bundled' | 'generated';
    source_hash?: string;
}

export interface LibraryItem extends LibraryReference {
    description: string;
    origin: 'bundled' | 'generated';
    status: string;
    smoke_passed: boolean;
    source_hash: string;
    parent_id?: string | null;
    created_at?: string | null;
    editable: boolean;
    deletable: boolean;
    source?: string;
}

export interface BackendConfig {
    default_endpoint: string;
    default_model: string;
    default_system_prompt: string;
    default_request_timeout_seconds: number;
    default_max_tool_rounds: number;
    default_sandbox_timeout_seconds: number;
    available_models: string[];
}

export interface CodeDocument {
    id: string;
    title: string;
    kind: 'prompt' | 'solver' | 'analysis' | 'visualization';
    language: 'markdown' | 'python' | 'typescript';
    source: string;
    readOnly: boolean;
    description?: string;
    status?: string;
    sourceHash?: string;
}

export interface ConfigStatus {
    state: 'loading' | 'ready' | 'error';
    message?: string;
}

export interface Conversation {
    id: string;
    title: string;
    created_at: string;
    updated_at: string;
    pinned: boolean;
    deleted_at?: string | null;
}
