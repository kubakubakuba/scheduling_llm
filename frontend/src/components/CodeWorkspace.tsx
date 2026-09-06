import { useEffect, useMemo, useState } from 'react';
import Editor, { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import type { CodeDocument } from '../types';

loader.config({ monaco });

interface CodeWorkspaceProps {
  isOpen: boolean;
  documents: CodeDocument[];
  selectedId?: string | null;
  onClose: () => void;
  onSavePrompt: (source: string) => Promise<void>;
}

function CodeIcon({ size = 17 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m8 9-3 3 3 3M16 9l3 3-3 3M14 5l-4 14" /></svg>;
}

function kindLabel(document: CodeDocument) {
  if (document.kind === 'prompt') return 'Prompt';
  if (document.kind === 'solver') return 'Solver';
  if (document.kind === 'visualization') return 'Applet';
  return 'Analysis';
}

export default function CodeWorkspace({ isOpen, documents, selectedId, onClose, onSavePrompt }: CodeWorkspaceProps) {
  const [activeId, setActiveId] = useState(selectedId || documents[0]?.id || 'system-prompt');
  const [promptDraft, setPromptDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeDocument = useMemo(() => documents.find((document) => document.id === activeId) || documents[0], [activeId, documents]);

  useEffect(() => {
    if (!isOpen) return;
    const nextId = selectedId && documents.some((document) => document.id === selectedId) ? selectedId : documents[0]?.id;
    if (nextId) setActiveId(nextId);
  }, [documents, isOpen, selectedId]);

  useEffect(() => {
    if (!isOpen) return;
    if (activeDocument?.kind === 'prompt') setPromptDraft(activeDocument.source);
    setError(null);
  }, [activeDocument, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  if (!isOpen || !activeDocument) return null;
  const isPrompt = activeDocument.kind === 'prompt';
  const displayedSource = isPrompt ? promptDraft : activeDocument.source;

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

  const copySource = async () => {
    try {
      await navigator.clipboard.writeText(displayedSource);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setError('Could not copy the source to the clipboard.');
    }
  };

  return <div className="code-workspace-backdrop" role="dialog" aria-modal="true" aria-label="Code workspace" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="code-workspace" onMouseDown={(event) => event.stopPropagation()}>
      <header className="code-workspace-header">
        <div><div className="code-workspace-title"><CodeIcon /> Code workspace</div><div className="code-workspace-subtitle">Inspect conversation sources and edit the active system prompt.</div></div>
        <button className="code-workspace-close" onClick={onClose} aria-label="Close code workspace">×</button>
      </header>
      <div className="code-workspace-body">
        <nav className="code-document-list" aria-label="Code documents">
          {documents.map((document) => <button key={document.id} className={`code-document-item ${document.id === activeDocument.id ? 'code-document-item-active' : ''}`} onClick={() => setActiveId(document.id)}>
            <span className="code-document-kind">{kindLabel(document)}</span>
            <span className="code-document-name">{document.title}</span>
            {document.status && <span className={`code-document-status code-document-status-${document.status}`}>{document.status}</span>}
          </button>)}
        </nav>
        <main className="code-editor-pane">
          <div className="code-editor-toolbar"><div><strong>{activeDocument.title}</strong>{activeDocument.description && <span>{activeDocument.description}</span>}</div><div className="code-editor-actions"><button onClick={copySource}>{copied ? 'Copied' : 'Copy'}</button>{isPrompt ? <><button onClick={() => setPromptDraft(activeDocument.source)} disabled={saving}>Cancel</button><button className="code-editor-save" onClick={savePrompt} disabled={saving}>{saving ? 'Saving…' : 'Save prompt'}</button></> : <span className="code-readonly-label">Read-only source</span>}</div></div>
          {error && <div className="code-editor-error" role="alert">{error}</div>}
          <div className="code-editor-container"><Editor height="100%" language={activeDocument.language} theme="vs-dark" value={displayedSource} onChange={(value) => isPrompt && setPromptDraft(value ?? '')} options={{ readOnly: !isPrompt, automaticLayout: true, minimap: { enabled: false }, fontSize: 13, lineNumbers: 'on', wordWrap: isPrompt ? 'on' : 'off', padding: { top: 12 } }} /></div>
        </main>
      </div>
    </section>
  </div>;
}
