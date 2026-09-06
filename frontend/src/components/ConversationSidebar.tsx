import { useState } from 'react';
import type { Conversation } from '../types';

interface Props {
    conversations: Conversation[];
    activeId: string | null;
    onSelect: (id: string) => void;
    onNew: () => void;
    onPin: (conversation: Conversation) => void;
    onTrash: (conversation: Conversation) => void;
    onRestore: (conversation: Conversation) => void;
    onPurge: (conversation: Conversation) => void;
    onRename: (conversation: Conversation, title: string) => void;
    trash: Conversation[];
    disabled?: boolean;
}

function PinIcon({ filled }: { filled: boolean }) {
    // Heroicons BookmarkIcon / BookmarkSlashIcon (24px outline). The
    // slashed form communicates that an already pinned chat can be removed.
    return <svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        {filled
            ? <path d="m3 3 1.664 1.664M21 21l-1.5-1.5m-5.485-1.242L12 17.25 4.5 21V8.742m.164-4.078a2.15 2.15 0 0 1 1.743-1.342 48.507 48.507 0 0 1 11.186 0c1.1.128 1.907 1.077 1.907 2.185V19.5M4.664 4.664 19.5 19.5" />
            : <path d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0 1 11.186 0Z" />}
    </svg>;
}

function TrashIcon() {
    // Heroicons TrashIcon (24px outline).
    return <svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" /></svg>;
}

function RestoreIcon() {
    return <svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v6h6" /><path d="M12 8v5l3 2" /></svg>;
}

export default function ConversationSidebar({ conversations, activeId, onSelect, onNew, onPin, onTrash, onRestore, onPurge, onRename, trash, disabled = false }: Props) {
    const [editingId, setEditingId] = useState<string | null>(null);
    const [editingTitle, setEditingTitle] = useState('');
    const pinned = conversations.filter((item) => item.pinned);
    const recent = conversations.filter((item) => !item.pinned);
    const beginRename = (conversation: Conversation) => {
        setEditingId(conversation.id);
        setEditingTitle(conversation.title || 'New conversation');
    };
    const finishRename = (conversation: Conversation) => {
        const title = editingTitle.trim();
        if (title && title !== conversation.title) onRename(conversation, title);
        setEditingId(null);
    };
    const render = (items: Conversation[]) => items.map((conversation) => (
        <div key={conversation.id} className={`conversation-item ${activeId === conversation.id ? 'conversation-item-active' : ''}`}>
            <div className="conversation-select" title={conversation.title}>
                {editingId === conversation.id ? <input className="conversation-title-input" value={editingTitle} autoFocus onChange={(event) => setEditingTitle(event.target.value)} onBlur={() => finishRename(conversation)} onKeyDown={(event) => { if (event.key === 'Enter') finishRename(conversation); if (event.key === 'Escape') setEditingId(null); }} disabled={disabled} /> : <button className="conversation-title-button" onClick={() => beginRename(conversation)} aria-label="Rename conversation" disabled={disabled}>{conversation.title || 'New conversation'}</button>}
                <button className="conversation-date-button" onClick={() => onSelect(conversation.id)} disabled={disabled}>{new Date(conversation.updated_at).toLocaleDateString()}</button>
            </div>
            <button className="conversation-action" onClick={() => onPin(conversation)} aria-label={conversation.pinned ? 'Unpin conversation' : 'Pin conversation'} disabled={disabled}><PinIcon filled={conversation.pinned} /></button>
            <button className="conversation-action" onClick={() => onTrash(conversation)} aria-label="Move conversation to trash" disabled={disabled}><TrashIcon /></button>
        </div>
    ));

    return (
        <aside className="conversation-sidebar">
            <div className="conversation-sidebar-brand">Scheduling assistant</div>
            <button className="new-chat-button" onClick={onNew} disabled={disabled}>＋ New chat</button>
            {pinned.length > 0 && <section className="conversation-section"><p className="sidebar-label">Pinned</p>{render(pinned)}</section>}
            <section className="conversation-section"><p className="sidebar-label">Recent</p>{recent.length ? render(recent) : <p className="conversation-empty">No conversations yet.</p>}</section>
            {trash.length > 0 && <section className="conversation-section"><p className="sidebar-label">Trash</p>{trash.map((conversation) => <div key={conversation.id} className="conversation-item"><span className="conversation-title conversation-trash-title">{conversation.title}</span><button className="conversation-action" onClick={() => onRestore(conversation)} aria-label="Restore conversation" disabled={disabled}><RestoreIcon /></button><button className="conversation-action" onClick={() => onPurge(conversation)} aria-label="Permanently delete conversation" disabled={disabled}><TrashIcon /></button></div>)}</section>}
        </aside>
    );
}
