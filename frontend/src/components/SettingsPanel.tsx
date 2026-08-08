import type { ChangeEvent } from 'react';
import type { Settings } from '../types';

interface SettingsPanelProps {
    isOpen: boolean;
    onClose: () => void;
    settings: Settings;
    onSettingsChange: (newSettings: Settings) => void;
    availableModels: string[];
}

export default function SettingsPanel({ isOpen, onClose, settings, onSettingsChange, availableModels }: SettingsPanelProps) {
    if (!isOpen) return null;

    const handleProviderChange = (e: ChangeEvent<HTMLSelectElement>) => {
        const provider = e.target.value;
        let newUri = settings.endpointUri;

        if (provider === 'OpenRouter') newUri = 'https://openrouter.ai/api/v1';
            else if (provider === 'OpenAI Direct') newUri = 'https://api.openai.com/v1';
                else if (provider === 'LM Studio') newUri = 'http://localhost:1234/v1';
                    else if (provider === 'Custom') newUri = '';

                    onSettingsChange({ ...settings, provider, endpointUri: newUri });
    };

    return (
        <div className="fixed inset-y-0 right-0 w-80 bg-zinc-950 border-l border-zinc-800 shadow-2xl z-50 flex flex-col transform transition-transform duration-300">
        <div className="flex items-center justify-between p-4 border-b border-zinc-800">
        <h2 className="text-sm font-semibold tracking-wide text-zinc-200">Configuration</h2>
        <button onClick={onClose} className="p-1 text-zinc-400 hover:text-zinc-100 transition-colors">
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
        </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
        <div>
        <label className="block text-xs font-medium text-zinc-400 mb-1.5">API Provider</label>
        <select
        value={settings.provider}
        onChange={handleProviderChange}
        className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
        >
        <option value="OpenRouter">OpenRouter</option>
        <option value="OpenAI Direct">OpenAI Direct</option>
        <option value="LM Studio">LM Studio (Local)</option>
        <option value="Custom">Custom Endpoint</option>
        </select>
        </div>

        <div>
        <label className="block text-xs font-medium text-zinc-400 mb-1.5">Endpoint URI</label>
        <input
        type="text"
        value={settings.endpointUri}
        onChange={(e) => onSettingsChange({ ...settings, endpointUri: e.target.value })}
        className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm font-mono text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors placeholder:text-zinc-700"
        />
        </div>

        <div>
        <label className="block text-xs font-medium text-zinc-400 mb-1.5">Model Name</label>
        <input
        type="text"
        list="model-options"
        value={settings.modelName}
        onChange={(e) => onSettingsChange({ ...settings, modelName: e.target.value })}
        className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm font-mono text-zinc-200 focus:outline-none focus:border-zinc-600 transition-colors"
        />
        <datalist id="model-options">
        {availableModels.map(model => <option key={model} value={model} />)}
        </datalist>
        </div>

        <div className="flex flex-col flex-1">
        <label className="block text-xs font-medium text-zinc-400 mb-1.5">System Prompt</label>
        <textarea
        value={settings.systemPrompt}
        onChange={(e) => onSettingsChange({ ...settings, systemPrompt: e.target.value })}
        rows={12}
        className="w-full bg-zinc-900 border border-zinc-800 rounded p-3 text-xs font-mono text-zinc-300 focus:outline-none focus:border-zinc-600 transition-colors resize-y leading-relaxed"
        />
        </div>
        </div>
        </div>
    );
}
