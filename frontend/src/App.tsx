import { lazy, Suspense, useState, useEffect, useMemo, useRef } from 'react';
import SettingsPanel from './components/SettingsPanel';
import ChatWindow from './components/ChatWindow';
import ConversationSidebar from './components/ConversationSidebar';
import { extractCodeDocuments, sourceDocumentId } from './codeDocuments';

const CodeWorkspace = lazy(() => import('./components/CodeWorkspace'));
import type { Settings, ChatMessage, BackendConfig, ConfigStatus, Conversation } from './types';

const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

const defaultSettings: Settings = {
  provider: 'OpenRouter',
  endpointUri: '',
  modelName: '',
  systemPrompt: '',
  requestTimeoutSeconds: 900,
  maxToolRounds: 32,
  sandboxTimeoutSeconds: 600,
};

function settingsFromBackend(value: Record<string, unknown>, previous: Settings): Settings {
  return {
    provider: typeof value.provider === 'string' ? value.provider : previous.provider,
    endpointUri: typeof value.endpoint_uri === 'string' ? value.endpoint_uri : previous.endpointUri,
    modelName: typeof value.model_name === 'string' ? value.model_name : previous.modelName,
    systemPrompt: typeof value.system_prompt === 'string' ? value.system_prompt : previous.systemPrompt,
    requestTimeoutSeconds: Number(value.request_timeout_seconds ?? previous.requestTimeoutSeconds ?? 900),
    maxToolRounds: Number(value.max_tool_rounds ?? previous.maxToolRounds ?? 32),
    sandboxTimeoutSeconds: Number(value.sandbox_timeout_seconds ?? previous.sandboxTimeoutSeconds ?? 600),
  };
}

export default function App() {
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isStopping, setIsStopping] = useState<boolean>(false);
  const [generationStatus, setGenerationStatus] = useState<{ stage: string; elapsedSeconds: number }>({ stage: 'thinking', elapsedSeconds: 0 });
  const [isSettingsOpen, setIsSettingsOpen] = useState<boolean>(false);
  const [instanceName, setInstanceName] = useState<string | null>(null);
  const [configStatus, setConfigStatus] = useState<ConfigStatus>({ state: 'loading' });
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [trashedConversations, setTrashedConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const activeGenerationId = useRef<string | null>(null);
  const [isCodeWorkspaceOpen, setIsCodeWorkspaceOpen] = useState(false);
  const [selectedCodeDocument, setSelectedCodeDocument] = useState<string | null>(null);
  const conversationLoaded = useRef(false);
  const elapsedAnchor = useRef({ seconds: 0, at: 0 });
  const settingsSaveTimer = useRef<number | null>(null);

  const codeDocuments = useMemo(() => extractCodeDocuments(messages, settings.systemPrompt), [messages, settings.systemPrompt]);

  useEffect(() => {
    if (!isLoading) return;
    const tick = () => {
      const now = performance.now();
      const elapsed = elapsedAnchor.current.seconds + Math.max(0, now - elapsedAnchor.current.at) / 1000;
      setGenerationStatus((previous) => ({ ...previous, elapsedSeconds: elapsed }));
    };
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [isLoading]);

  useEffect(() => () => {
    if (settingsSaveTimer.current !== null) window.clearTimeout(settingsSaveTimer.current);
  }, []);

  const errorMessage = (payload: unknown, fallback: string) => {
    if (!payload || typeof payload !== 'object' || !('detail' in payload)) return fallback;

    const detail = payload.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') {
      return detail.message;
    }

    return fallback;
  };

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/config`)
    .then(res => {
      if (!res.ok) throw new Error(`Configuration request failed (${res.status}).`);
      return res.json();
    })
    .then((data: BackendConfig) => {
      if (!data.default_endpoint || !data.default_model) {
        throw new Error('The backend returned an incomplete model configuration.');
      }

      if (!conversationLoaded.current) {
        setSettings({
          provider: 'OpenRouter',
          endpointUri: data.default_endpoint,
          modelName: data.default_model,
          systemPrompt: data.default_system_prompt,
          requestTimeoutSeconds: data.default_request_timeout_seconds ?? 900,
          maxToolRounds: data.default_max_tool_rounds ?? 32,
          sandboxTimeoutSeconds: data.default_sandbox_timeout_seconds ?? 600,
        });
      }
      setAvailableModels(data.available_models ?? []);
      setConfigStatus({ state: 'ready' });
    })
    .catch(err => {
      const message = err instanceof Error ? err.message : 'Could not load the model configuration.';
      console.error('Failed to load config:', err);
      setConfigStatus({ state: 'error', message: `${message} Open settings or check the backend configuration.` });
    });
  }, []);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/conversations?include_trash=true`)
      .then((res) => res.json())
      .then(async (data) => {
        const allItems = (data.conversations ?? []) as Conversation[];
        const items = allItems.filter((item) => !item.deleted_at);
        setTrashedConversations(allItems.filter((item) => item.deleted_at));
        setConversations(items);
        if (items.length) {
          conversationLoaded.current = true;
          const selected = items[0];
          const detail = await fetch(`${API_BASE_URL}/api/conversations/${selected.id}`).then((res) => res.json());
          setConversationId(selected.id);
          setMessages((detail.messages ?? []) as ChatMessage[]);
          setInstanceName(detail.workspace?.instance?.instance_name ?? null);
          setSettings((previous) => settingsFromBackend(detail.settings ?? {}, previous));
        } else {
          conversationLoaded.current = true;
          const created = await fetch(`${API_BASE_URL}/api/conversations`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then((res) => res.json());
          setConversationId(created.id);
          setConversations([created]);
        }
      })
      .catch((error) => console.error('Failed to load conversations:', error));
  }, []);

  const handleFileUpload = async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);

    try {
    const res = await fetch(`${API_BASE_URL}/api/upload?conversation_id=${encodeURIComponent(conversationId ?? '')}`, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(errorMessage(data, 'The instance could not be loaded.'));
      }

      setInstanceName(file.name.replace(/\.json$/i, ''));
      if (!conversationId && data.conversation_id) {
        const detail = await fetch(`${API_BASE_URL}/api/conversations/${data.conversation_id}`).then((response) => response.json());
        setConversationId(data.conversation_id);
        setConversations((previous) => [detail, ...previous.filter((item) => item.id !== data.conversation_id)]);
      }
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `[System] ${data.message}. The instance is now loaded into memory.` }
      ]);
    } catch (error) {
      console.error('File upload failed:', error);
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `**Upload failed:** ${error instanceof Error ? error.message : 'Could not load the JSON instance.'}` }
      ]);
    }
  };

  const handleNewChat = async () => {
    if (isLoading) return;
    const created = await fetch(`${API_BASE_URL}/api/conversations`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...settings, endpoint_uri: settings.endpointUri, model_name: settings.modelName, request_timeout_seconds: settings.requestTimeoutSeconds, max_tool_rounds: settings.maxToolRounds, sandbox_timeout_seconds: settings.sandboxTimeoutSeconds }) }).then((res) => res.json());
    setConversationId(created.id);
    setConversations((previous) => [created, ...previous]);
    setMessages([]);
    setInstanceName(null);
  };

  const handleSelectConversation = async (id: string) => {
    if (isLoading) return;
    const detail = await fetch(`${API_BASE_URL}/api/conversations/${id}`).then((res) => res.json());
    setConversationId(id);
    setMessages((detail.messages ?? []) as ChatMessage[]);
    setSettings((previous) => settingsFromBackend(detail.settings ?? {}, previous));
    setInstanceName(detail.workspace?.instance?.instance_name ?? null);
  };

  const handlePin = async (conversation: Conversation) => {
    const updated = await fetch(`${API_BASE_URL}/api/conversations/${conversation.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pinned: !conversation.pinned }) }).then((res) => res.json());
    setConversations((previous) => previous.map((item) => item.id === updated.id ? updated : item));
  };

  const handleRename = async (conversation: Conversation, title: string) => {
    const updated = await fetch(`${API_BASE_URL}/api/conversations/${conversation.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) }).then((res) => res.json());
    setConversations((previous) => previous.map((item) => item.id === updated.id ? updated : item));
  };

  const handleTrash = async (conversation: Conversation) => {
    const response = await fetch(`${API_BASE_URL}/api/conversations/${conversation.id}`, { method: 'DELETE' });
    if (!response.ok) throw new Error(`Could not move “${conversation.title}” to trash.`);
    const deletedAt = new Date().toISOString();
    setConversations((previous) => previous.filter((item) => item.id !== conversation.id));
    setTrashedConversations((previous) => [
      { ...conversation, deleted_at: deletedAt, pinned: false },
      ...previous.filter((item) => item.id !== conversation.id),
    ]);
    if (conversation.id === conversationId) {
      const remaining = conversations.filter((item) => item.id !== conversation.id);
      const nextConversation = remaining[0];
      if (nextConversation) {
        await handleSelectConversation(nextConversation.id);
      } else {
        setConversationId(null);
        setMessages([]);
        setInstanceName(null);
      }
    }
  };

  const handleRestore = async (conversation: Conversation) => {
    const response = await fetch(`${API_BASE_URL}/api/conversations/${conversation.id}/restore`, { method: 'POST' });
    if (!response.ok) throw new Error(`Could not restore “${conversation.title}”.`);
    const restored = { ...conversation, deleted_at: null };
    setTrashedConversations((previous) => previous.filter((item) => item.id !== conversation.id));
    setConversations((previous) => [restored, ...previous.filter((item) => item.id !== conversation.id)]);
  };

  const handlePurge = async (conversation: Conversation) => {
    const response = await fetch(`${API_BASE_URL}/api/conversations/${conversation.id}/purge`, { method: 'DELETE' });
    if (!response.ok) throw new Error(`Could not permanently delete “${conversation.title}”.`);
    setTrashedConversations((previous) => previous.filter((item) => item.id !== conversation.id));
  };

  const handleSettingsChange = (nextSettings: Settings) => {
    const normalized = {
      ...nextSettings,
      requestTimeoutSeconds: Math.max(60, Math.min(3600, Math.round(Number(nextSettings.requestTimeoutSeconds) || 900))),
      maxToolRounds: Math.max(1, Math.min(128, Math.round(Number(nextSettings.maxToolRounds) || 32))),
      sandboxTimeoutSeconds: Math.max(60, Math.min(3600, Math.round(Number(nextSettings.sandboxTimeoutSeconds) || 600))),
    };
    setSettings(normalized);

    if (!normalized.endpointUri.trim() || !normalized.modelName.trim()) {
      setConfigStatus({
        state: 'error',
        message: 'An endpoint and model are required before sending a message.'
      });
    } else if (configStatus.state === 'error') {
      setConfigStatus({ state: 'ready' });
    }

    if (conversationId) {
      if (settingsSaveTimer.current !== null) window.clearTimeout(settingsSaveTimer.current);
      settingsSaveTimer.current = window.setTimeout(() => {
        void fetch(`${API_BASE_URL}/api/conversations/${conversationId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ settings: { provider: normalized.provider, endpoint_uri: normalized.endpointUri, model_name: normalized.modelName, system_prompt: normalized.systemPrompt, request_timeout_seconds: normalized.requestTimeoutSeconds, max_tool_rounds: normalized.maxToolRounds, sandbox_timeout_seconds: normalized.sandboxTimeoutSeconds } }),
        });
      }, 350);
    }
  };

  const openCodeWorkspace = (documentId?: string | null) => {
    setSelectedCodeDocument(documentId ?? 'system-prompt');
    setIsCodeWorkspaceOpen(true);
    setIsSettingsOpen(false);
  };

  const saveSystemPrompt = async (systemPrompt: string) => {
    const nextSettings = { ...settings, systemPrompt };
    if (conversationId) {
      const response = await fetch(`${API_BASE_URL}/api/conversations/${conversationId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: { provider: nextSettings.provider, endpoint_uri: nextSettings.endpointUri, model_name: nextSettings.modelName, system_prompt: systemPrompt, request_timeout_seconds: nextSettings.requestTimeoutSeconds, max_tool_rounds: nextSettings.maxToolRounds, sandbox_timeout_seconds: nextSettings.sandboxTimeoutSeconds } }),
      });
      if (!response.ok) throw new Error('The system prompt could not be saved.');
    }
    setSettings(nextSettings);
  };

  const handleSendMessage = async (content: string) => {
    if (configStatus.state !== 'ready') {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `**Configuration unavailable:** ${configStatus.message ?? 'The model connection is still loading.'}`
      }]);
      return;
    }

    const userMessage: ChatMessage = { role: 'user', content };
    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);
    setIsStopping(false);
    setGenerationStatus({ stage: 'thinking', elapsedSeconds: 0 });
    elapsedAnchor.current = { seconds: 0, at: performance.now() };
    const generationId = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    activeGenerationId.current = generationId;

    try {
      let activeConversationId = conversationId;
      if (!activeConversationId) {
        const createResponse = await fetch(`${API_BASE_URL}/api/conversations`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...settings, endpoint_uri: settings.endpointUri, model_name: settings.modelName, request_timeout_seconds: settings.requestTimeoutSeconds, max_tool_rounds: settings.maxToolRounds, sandbox_timeout_seconds: settings.sandboxTimeoutSeconds }),
        });
        const created = await createResponse.json();
        if (!createResponse.ok || !created.id) throw new Error('Could not create a conversation.');
        activeConversationId = created.id;
        setConversationId(created.id);
        setConversations((previous) => [created, ...previous.filter((item) => item.id !== created.id)]);
      }
      const res = await fetch(`${API_BASE_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: content,
          conversation_id: activeConversationId,
          generation_id: generationId,
          provider: settings.provider,
          endpoint_uri: settings.endpointUri,
          model_name: settings.modelName,
          system_prompt: settings.systemPrompt,
          request_timeout_seconds: settings.requestTimeoutSeconds,
          max_tool_rounds: settings.maxToolRounds,
          sandbox_timeout_seconds: settings.sandboxTimeoutSeconds,
        })
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(errorMessage(data, `Backend request failed (${res.status}).`));
      }
      if (!res.body) throw new Error('The backend returned an empty response.');

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
            if (parsed.type === 'status') {
              const seconds = Number(parsed.elapsed_seconds) || 0;
              elapsedAnchor.current = { seconds, at: performance.now() };
              setGenerationStatus({ stage: parsed.stage || 'thinking', elapsedSeconds: seconds });
            } else if (parsed.type === 'cancelled') {
              setMessages(prev => [...prev, { role: 'assistant', content: parsed.detail || 'Generation stopped by user.', incomplete: true, status: 'cancelled', generation_id: generationId }]);
            } else if (parsed.type === 'error') {
              console.error(parsed.detail);
              setMessages(prev => [...prev, { role: 'assistant', content: `**Request failed:** ${parsed.detail}` }]);
            } else if (parsed.type === 'message') {
              if (parsed.data?.tool_calls?.length) setGenerationStatus((previous) => ({ ...previous, stage: 'running tool' }));
              setMessages(prev => [...prev, parsed.data]);
            }
          }
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      console.error('Failed to send message:', error);
      setMessages(prev => [...prev, { role: 'assistant', content: `**Request failed:** ${error instanceof Error ? error.message : 'Could not communicate with the backend service.'}` }]);
    } finally {
      setIsLoading(false);
      setIsStopping(false);
      activeGenerationId.current = null;
    }
  };

  const handleStopGeneration = async () => {
    const generationId = activeGenerationId.current;
    if (!generationId || !conversationId || isStopping) return;
    setIsStopping(true);
    setGenerationStatus((previous) => ({ ...previous, stage: 'stopping' }));
    try {
      const response = await fetch(`${API_BASE_URL}/api/conversations/${conversationId}/generations/${generationId}/stop`, { method: 'POST' });
      if (!response.ok) throw new Error(`Stop request failed (${response.status}).`);
    } catch (error) {
      console.error('Failed to stop generation:', error);
      setIsStopping(false);
      setMessages(prev => [...prev, { role: 'assistant', content: `**Stop failed:** ${error instanceof Error ? error.message : 'Could not stop the generation.'}` }]);
    }
  };

  return (
    <div className="relative flex h-screen w-screen overflow-hidden bg-[#121212] font-sans antialiased text-zinc-100">

    {/* Code workspace and configuration controls */}
    <button
    onClick={() => openCodeWorkspace('system-prompt')}
    className="absolute top-4 right-14 z-40 p-2 text-zinc-500 hover:text-zinc-200 bg-[#1a1a1a] border border-zinc-800 rounded-md transition-colors shadow-sm"
    aria-label="Open code workspace"
    title="Code workspace"
    >
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="m8 9-3 3 3 3M16 9l3 3-3 3M14 5l-4 14" /></svg>
    </button>
    <button
    onClick={() => setIsSettingsOpen(true)}
    className="absolute top-4 right-4 z-40 p-2 text-zinc-500 hover:text-zinc-200 bg-[#1a1a1a] border border-zinc-800 rounded-md transition-colors shadow-sm"
    >
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
    </button>

    <ConversationSidebar conversations={conversations} trash={trashedConversations} activeId={conversationId} onSelect={handleSelectConversation} onNew={handleNewChat} onPin={handlePin} onTrash={handleTrash} onRestore={handleRestore} onPurge={handlePurge} onRename={handleRename} disabled={isLoading} />
    <ChatWindow
    messages={messages}
    conversationId={conversationId}
    onSendMessage={handleSendMessage}
    onFileUpload={handleFileUpload}
    onNewChat={handleNewChat}
    instanceName={instanceName}
    configStatus={configStatus}
    isLoading={isLoading}
    isStopping={isStopping}
    generationStatus={generationStatus}
    onStop={handleStopGeneration}
    onOpenSource={(toolCall) => openCodeWorkspace(sourceDocumentId(toolCall))}
    />

    <SettingsPanel
    isOpen={isSettingsOpen}
    onClose={() => setIsSettingsOpen(false)}
    settings={settings}
    onSettingsChange={handleSettingsChange}
    onEditSystemPrompt={() => openCodeWorkspace('system-prompt')}
    availableModels={availableModels}
    />

    {/* Backdrop for Settings Panel */}
    {isSettingsOpen && (
      <div
      className="fixed inset-0 bg-black/40 z-40 transition-opacity"
      onClick={() => setIsSettingsOpen(false)}
      />
    )}
    <Suspense fallback={null}>
      <CodeWorkspace
        isOpen={isCodeWorkspaceOpen}
        documents={codeDocuments}
        selectedId={selectedCodeDocument}
        onClose={() => setIsCodeWorkspaceOpen(false)}
        onSavePrompt={saveSystemPrompt}
      />
    </Suspense>
    </div>
  );
}
