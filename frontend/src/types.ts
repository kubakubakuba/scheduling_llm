export interface Settings {
    provider: string;
    endpointUri: string;
    modelName: string;
    systemPrompt: string;
}

export interface ChatMessage {
    role: 'user' | 'assistant' | 'system' | 'tool';
    content: string;
    tool_call_id?: string;
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

export interface Settings {
    provider: string;
    endpointUri: string;
    modelName: string;
    systemPrompt: string;
}

export interface ChatMessage {
    role: 'user' | 'assistant' | 'system' | 'tool';
    content: string;
    reasoning?: string | null;
    tool_calls?: Array<{
        id: string;
        type: string;
        function: { name: string; arguments: string };
    }>;
    tool_call_id?: string;
    name?: string;
}

export interface BackendConfig {
    default_endpoint: string;
    default_model: string;
    default_system_prompt: string;
    available_models: string[];
}
