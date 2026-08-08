import { useState, useEffect } from 'react';
import SettingsPanel from './components/SettingsPanel';
import ChatWindow from './components/ChatWindow';
import type { Settings, ChatMessage, BackendConfig } from './types';

const defaultSettings: Settings = {
  provider: 'OpenRouter',
  endpointUri: '',
  modelName: '',
  systemPrompt: ''
};

export default function App() {
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState<boolean>(false);

  useEffect(() => {
    fetch('http://localhost:8000/api/config')
    .then(res => res.json())
    .then((data: BackendConfig) => {
      setSettings({
        provider: 'OpenRouter',
        endpointUri: data.default_endpoint,
        modelName: data.default_model,
        systemPrompt: data.default_system_prompt
      });
      setAvailableModels(data.available_models);
    })
    .catch(err => console.error('Failed to load config:', err));
  }, []);

  const handleFileUpload = async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('http://localhost:8000/api/upload', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `[System] ${data.message}. The instance is now loaded into memory.` }
      ]);
    } catch (error) {
      console.error('File upload failed:', error);
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: '[System Error] Failed to upload the JSON instance.' }
      ]);
    }
  };

  const handleSendMessage = async (content: string) => {
    const userMessage: ChatMessage = { role: 'user', content };
    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const res = await fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: content,
          endpoint_uri: settings.endpointUri,
          model_name: settings.modelName,
          system_prompt: settings.systemPrompt,
          // Pass messages at the current state, excluding the new user message
          history: messages
        })
      });

      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');

        // Keep the last incomplete line in the buffer
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.trim()) {
            const parsed = JSON.parse(line);
            if (parsed.type === 'error') {
              console.error(parsed.detail);
              setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${parsed.detail}` }]);
            } else if (parsed.type === 'message') {
              setMessages(prev => [...prev, parsed.data]);
            }
          }
        }
      }
    } catch (error) {
      console.error('Failed to send message:', error);
      setMessages(prev => [...prev, { role: 'assistant', content: 'Error communicating with backend service.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative flex h-screen w-screen overflow-hidden bg-[#121212] font-sans antialiased text-zinc-100">

    {/* Top right gear icon */}
    <button
    onClick={() => setIsSettingsOpen(true)}
    className="absolute top-4 right-4 z-40 p-2 text-zinc-500 hover:text-zinc-200 bg-[#1a1a1a] border border-zinc-800 rounded-md transition-colors shadow-sm"
    >
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
    </button>

    <ChatWindow
    messages={messages}
    onSendMessage={handleSendMessage}
    onFileUpload={handleFileUpload}
    isLoading={isLoading}
    />

    <SettingsPanel
    isOpen={isSettingsOpen}
    onClose={() => setIsSettingsOpen(false)}
    settings={settings}
    onSettingsChange={setSettings}
    availableModels={availableModels}
    />

    {/* Backdrop for Settings Panel */}
    {isSettingsOpen && (
      <div
      className="fixed inset-0 bg-black/40 z-40 transition-opacity"
      onClick={() => setIsSettingsOpen(false)}
      />
    )}
    </div>
  );
}
