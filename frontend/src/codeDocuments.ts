import type { ChatMessage, CodeDocument } from './types';

function jsonObject(value: string | undefined): Record<string, unknown> | null {
  if (!value) return null;
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function sourceFromArguments(raw: string) {
  const parsed = jsonObject(raw);
  return typeof parsed?.source === 'string' ? parsed.source : null;
}

export function sourceDocumentId(toolCall: { id: string; function: { name: string } }) {
  if (toolCall.function.name === 'get_solver_source') return `solver-base-${toolCall.id}`;
  if (toolCall.function.name === 'write_solver_variant') return `solver-variant-${toolCall.id}`;
  if (toolCall.function.name === 'write_analysis_script') return `analysis-${toolCall.id}`;
  if (toolCall.function.name === 'write_visualization_applet') return `visualization-${toolCall.id}`;
  return null;
}

export function extractCodeDocuments(messages: ChatMessage[], systemPrompt: string): CodeDocument[] {
  const documents: CodeDocument[] = [{
    id: 'system-prompt',
    title: 'System prompt',
    kind: 'prompt',
    language: 'markdown',
    source: systemPrompt,
    readOnly: false,
  }];
  const toolResults = new Map<string, Record<string, unknown>>();
  for (const message of messages) {
    if (message.role !== 'tool' || !message.tool_call_id) continue;
    const payload = jsonObject(message.content);
    if (payload) toolResults.set(message.tool_call_id, payload);
  }

  for (const message of messages) {
    if (message.role !== 'assistant' || !message.tool_calls) continue;
    for (const call of message.tool_calls) {
      const id = sourceDocumentId(call);
      if (!id) continue;
      const result = toolResults.get(call.id);
      const args = jsonObject(call.function.arguments);
      let source: string | null = null;
      let title = call.function.name;
      let kind: CodeDocument['kind'] = call.function.name === 'write_analysis_script' ? 'analysis' : call.function.name === 'write_visualization_applet' ? 'visualization' : 'solver';
      let description: string | undefined;
      if (call.function.name === 'get_solver_source') {
        source = typeof result?.source === 'string' ? result.source : null;
        title = 'Base solver';
      } else if (call.function.name === 'write_solver_variant') {
        source = sourceFromArguments(call.function.arguments);
        title = typeof args?.name === 'string' ? `Solver: ${args.name}` : 'Solver variant';
        description = typeof args?.description === 'string' ? args.description : undefined;
      } else if (call.function.name === 'write_analysis_script') {
        source = sourceFromArguments(call.function.arguments);
        title = typeof args?.name === 'string' ? `Analysis: ${args.name}` : 'Analysis script';
        description = typeof args?.description === 'string' ? args.description : undefined;
      } else {
        source = sourceFromArguments(call.function.arguments);
        title = typeof args?.name === 'string' ? `Visualization: ${args.name}` : 'Visualization applet';
        description = typeof args?.description === 'string' ? args.description : undefined;
      }
      if (!source) continue;
      documents.push({
        id,
        title,
        kind,
        language: kind === 'visualization' ? 'typescript' : 'python',
        source,
        readOnly: true,
        description,
        status: typeof result?.status === 'string' ? result.status : undefined,
        sourceHash: typeof result?.base_hash === 'string' ? result.base_hash : undefined,
      });
    }
  }
  return documents;
}
