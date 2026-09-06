import { useEffect, useMemo, useState } from 'react';
import Editor, { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import type { CodeDocument, LibraryItem, LibraryReference } from '../types';

loader.config({ monaco });

type WorkspaceSection = 'library' | 'conversation' | 'prompt';
type LibraryFilter = 'all' | 'analysis' | 'visualization';

interface CodeWorkspaceProps {
  isOpen: boolean;
  documents: CodeDocument[];
  selectedId?: string | null;
  initialSection: WorkspaceSection;
  mutationsDisabled: boolean;
  onClose: () => void;
  onSavePrompt: (source: string) => Promise<void>;
  onAttach: (item: LibraryReference) => void;
  onDeleted: (item: LibraryReference) => void;
}

const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

function CodeIcon({ size = 17 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m8 9-3 3 3 3M16 9l3 3-3 3M14 5l-4 14" /></svg>;
}

function kindLabel(document: CodeDocument) {
  if (document.kind === 'prompt') return 'Prompt';
  if (document.kind === 'solver') return 'Solver';
  if (document.kind === 'visualization') return 'Applet';
  return 'Analysis';
}

function libraryKindLabel(kind: LibraryItem['kind']) {
  return kind === 'analysis' ? 'Analysis' : 'Applet';
}

function errorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== 'object' || !('detail' in payload)) return fallback;
  const detail = payload.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') {
    if ('message' in detail && typeof detail.message === 'string') return detail.message;
    if ('validation_errors' in detail && Array.isArray(detail.validation_errors)) return detail.validation_errors.map(String).join('\n');
  }
  return fallback;
}

export default function CodeWorkspace({ isOpen, documents, selectedId, initialSection, mutationsDisabled, onClose, onSavePrompt, onAttach, onDeleted }: CodeWorkspaceProps) {
  const [section, setSection] = useState<WorkspaceSection>(initialSection);
  const [activeDocumentId, setActiveDocumentId] = useState(selectedId || 'system-prompt');
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [activeLibraryKey, setActiveLibraryKey] = useState<string | null>(null);
  const [activeItem, setActiveItem] = useState<LibraryItem | null>(null);
  const [filter, setFilter] = useState<LibraryFilter>('all');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draftSource, setDraftSource] = useState('');
  const [draftName, setDraftName] = useState('');
  const [draftDescription, setDraftDescription] = useState('');
  const [promptDraft, setPromptDraft] = useState(documents.find((document) => document.kind === 'prompt')?.source || '');
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const promptDocument = useMemo(() => documents.find((document) => document.kind === 'prompt'), [documents]);
  const conversationDocuments = useMemo(() => documents.filter((document) => document.kind !== 'prompt'), [documents]);
  const activeDocument = useMemo(() => conversationDocuments.find((document) => document.id === activeDocumentId) || conversationDocuments[0], [activeDocumentId, conversationDocuments]);
  const libraryKey = (item: Pick<LibraryItem, 'kind' | 'id'>) => `${item.kind}:${item.id}`;
  const dirtyLibraryDraft = Boolean(editing && activeItem && (draftSource !== activeItem.source || draftName !== activeItem.name || draftDescription !== activeItem.description));
  const dirtyPromptDraft = Boolean(section === 'prompt' && promptDocument && promptDraft !== promptDocument.source);

  const mayDiscard = () => !(dirtyLibraryDraft || dirtyPromptDraft) || window.confirm('Discard the unsaved changes?');

  const loadLibrary = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filter !== 'all') params.set('kind', filter);
      if (query.trim()) params.set('query', query.trim());
      const response = await fetch(`${API_BASE_URL}/api/library/items?${params}`);
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorMessage(payload, 'Could not load the source library.'));
      const nextItems = (payload?.items || []) as LibraryItem[];
      setItems(nextItems);
      setActiveLibraryKey((current) => current && nextItems.some((item) => libraryKey(item) === current) ? current : nextItems[0] ? libraryKey(nextItems[0]) : null);
      if (!nextItems.length) setActiveItem(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load the source library.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!isOpen || section !== 'library') return;
    const timer = window.setTimeout(() => { void loadLibrary(); }, 150);
    return () => window.clearTimeout(timer);
  // loadLibrary intentionally follows the current filter/search values.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, isOpen, query, section]);

  useEffect(() => {
    if (!isOpen || section !== 'library' || !activeLibraryKey) return;
    const [kind, ...idParts] = activeLibraryKey.split(':');
    const itemId = idParts.join(':');
    let cancelled = false;
    fetch(`${API_BASE_URL}/api/library/items/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`)
      .then(async (response) => {
        const payload = await response.json().catch(() => null);
        if (!response.ok) throw new Error(errorMessage(payload, 'Could not load the library source.'));
        return payload as LibraryItem;
      })
      .then((item) => {
        if (cancelled) return;
        setActiveItem(item);
        setDraftName(item.name);
        setDraftDescription(item.description);
        setDraftSource(item.source || '');
        setEditing(false);
        setError(null);
      })
      .catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'Could not load the library source.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [activeLibraryKey, isOpen, section]);

  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && mayDiscard()) onClose();
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  });

  if (!isOpen) return null;

  const switchSection = (next: WorkspaceSection) => {
    if (!mayDiscard()) return;
    setEditing(false);
    setError(null);
    setSection(next);
    if (next === 'prompt' && promptDocument) setPromptDraft(promptDocument.source);
  };

  const selectLibraryItem = (item: LibraryItem) => {
    if (!mayDiscard()) return;
    setEditing(false);
    setActiveLibraryKey(libraryKey(item));
  };

  const savePrompt = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSavePrompt(promptDraft);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save the system prompt.');
    } finally {
      setSaving(false);
    }
  };

  const saveVersion = async () => {
    if (!activeItem) return;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/api/library/items/${encodeURIComponent(activeItem.kind)}/${encodeURIComponent(activeItem.id)}/versions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: draftName, description: draftDescription, source: draftSource }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorMessage(payload, 'The new version could not be saved.'));
      const created = payload as LibraryItem;
      setEditing(false);
      await loadLibrary();
      setActiveLibraryKey(libraryKey(created));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The new version could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const deleteItem = async () => {
    if (!activeItem?.deletable || !window.confirm(`Permanently delete “${activeItem.name}”? Existing rendered visualizations will remain in their conversations.`)) return;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/api/library/items/${encodeURIComponent(activeItem.kind)}/${encodeURIComponent(activeItem.id)}`, { method: 'DELETE' });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorMessage(payload, 'The library item could not be deleted.'));
      onDeleted(activeItem);
      setActiveItem(null);
      setActiveLibraryKey(null);
      await loadLibrary();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The library item could not be deleted.');
    } finally {
      setSaving(false);
    }
  };

  const displayedSource = section === 'library' ? (editing ? draftSource : activeItem?.source || '') : section === 'prompt' ? promptDraft : activeDocument?.source || '';
  const copySource = async () => {
    try {
      await navigator.clipboard.writeText(displayedSource);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setError('Could not copy the source to the clipboard.');
    }
  };

  const title = section === 'library' ? activeItem?.name : section === 'prompt' ? 'System prompt' : activeDocument?.title;
  const description = section === 'library' ? activeItem?.description : section === 'conversation' ? activeDocument?.description : 'Instructions used for this conversation.';
  const language = section === 'library' ? (activeItem?.kind === 'visualization' ? 'typescript' : 'python') : section === 'prompt' ? 'markdown' : activeDocument?.language || 'python';

  return <div className="code-workspace-backdrop" role="dialog" aria-modal="true" aria-label="Code workspace" onMouseDown={(event) => { if (event.target === event.currentTarget && mayDiscard()) onClose(); }}>
    <section className="code-workspace" onMouseDown={(event) => event.stopPropagation()}>
      <header className="code-workspace-header">
        <div><div className="code-workspace-title"><CodeIcon /> Code library</div><div className="code-workspace-subtitle">Inspect reusable sources, preserve conversation code, and manage the active prompt.</div></div>
        <button className="code-workspace-close" onClick={() => { if (mayDiscard()) onClose(); }} aria-label="Close code workspace">×</button>
      </header>
      <div className="code-workspace-tabs" role="tablist">
        <button className={section === 'library' ? 'active' : ''} onClick={() => switchSection('library')}>Library</button>
        <button className={section === 'conversation' ? 'active' : ''} onClick={() => switchSection('conversation')}>Conversation sources</button>
        <button className={section === 'prompt' ? 'active' : ''} onClick={() => switchSection('prompt')}>System prompt</button>
      </div>
      {section === 'library' && <div className="library-controls"><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search scripts and applets…" aria-label="Search source library" /><div className="library-filter">{(['all', 'analysis', 'visualization'] as LibraryFilter[]).map((value) => <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{value === 'visualization' ? 'Applets' : value[0].toUpperCase() + value.slice(1)}</button>)}</div></div>}
      <div className="code-workspace-body">
        <nav className="code-document-list" aria-label={section === 'library' ? 'Library items' : 'Code documents'}>
          {section === 'library' && items.map((item) => <button key={libraryKey(item)} className={`code-document-item ${libraryKey(item) === activeLibraryKey ? 'code-document-item-active' : ''}`} onClick={() => selectLibraryItem(item)}>
            <span className="code-document-item-heading"><span className="code-document-kind">{libraryKindLabel(item.kind)}</span><span className={`library-origin library-origin-${item.origin}`}>{item.origin}</span></span>
            <span className="code-document-name">{item.name}</span>
            <span className={`code-document-status ${item.smoke_passed ? '' : 'code-document-status-unchecked'}`}>{item.status} · {item.smoke_passed ? 'tested' : 'unchecked'}</span>
          </button>)}
          {section === 'library' && !loading && items.length === 0 && <p className="code-document-empty">No matching library items.</p>}
          {section === 'conversation' && conversationDocuments.map((document) => <button key={document.id} className={`code-document-item ${document.id === activeDocument?.id ? 'code-document-item-active' : ''}`} onClick={() => setActiveDocumentId(document.id)}>
            <span className="code-document-kind">{kindLabel(document)}</span><span className="code-document-name">{document.title}</span>{document.status && <span className={`code-document-status code-document-status-${document.status}`}>{document.status}</span>}
          </button>)}
          {section === 'conversation' && conversationDocuments.length === 0 && <p className="code-document-empty">No source has been generated in this conversation.</p>}
          {section === 'prompt' && promptDocument && <button className="code-document-item code-document-item-active"><span className="code-document-kind">Prompt</span><span className="code-document-name">System prompt</span></button>}
        </nav>
        <main className="code-editor-pane">
          <div className="code-editor-toolbar">
            <div className="code-editor-heading">{section === 'library' && editing ? <><input value={draftName} onChange={(event) => setDraftName(event.target.value)} aria-label="Library item name" /><input value={draftDescription} onChange={(event) => setDraftDescription(event.target.value)} aria-label="Library item description" /></> : <><strong>{title || (loading ? 'Loading…' : 'Nothing selected')}</strong>{description && <span>{description}</span>}{activeItem?.parent_id && section === 'library' && <span>Based on {activeItem.parent_id}</span>}</>}</div>
            <div className="code-editor-actions">
              {displayedSource && <button onClick={copySource}>{copied ? 'Copied' : 'Copy'}</button>}
              {section === 'library' && activeItem && !editing && <><button className="code-editor-use" onClick={() => onAttach(activeItem)}>Use in chat</button><button onClick={() => setEditing(true)} disabled={mutationsDisabled}>Edit</button>{activeItem.deletable && <button className="code-editor-delete" onClick={deleteItem} disabled={saving || mutationsDisabled}>Delete</button>}</>}
              {section === 'library' && activeItem && editing && <><button onClick={() => { setEditing(false); setDraftName(activeItem.name); setDraftDescription(activeItem.description); setDraftSource(activeItem.source || ''); }} disabled={saving}>Cancel</button><button className="code-editor-save" onClick={saveVersion} disabled={saving || mutationsDisabled || !draftName.trim()}>{saving ? 'Validating…' : 'Save new version'}</button></>}
              {section === 'conversation' && activeDocument && <span className="code-readonly-label">Archived source</span>}
              {section === 'prompt' && <><button onClick={() => setPromptDraft(promptDocument?.source || '')} disabled={saving}>Cancel</button><button className="code-editor-save" onClick={savePrompt} disabled={saving}>{saving ? 'Saving…' : 'Save prompt'}</button></>}
            </div>
          </div>
          {error && <div className="code-editor-error" role="alert">{error}</div>}
          <div className="code-editor-container"><Editor height="100%" language={language} theme="vs-dark" value={displayedSource} onChange={(value) => { if (section === 'library' && editing) setDraftSource(value ?? ''); if (section === 'prompt') setPromptDraft(value ?? ''); }} options={{ readOnly: section === 'conversation' || section === 'library' && !editing, automaticLayout: true, minimap: { enabled: false }, fontSize: 13, lineNumbers: 'on', wordWrap: section === 'prompt' ? 'on' : 'off', padding: { top: 12 } }} /></div>
        </main>
      </div>
    </section>
  </div>;
}
