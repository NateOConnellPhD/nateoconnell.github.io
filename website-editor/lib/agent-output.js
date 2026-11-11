// Only user-facing assistant messages belong in the conversation. Never expose
// reasoning items, tool arguments, environment configuration, or raw events.
export function assistantMessages(items, turnId) {
  return items.filter(item => item.type === 'message' && item.role === 'assistant' && (!turnId || item.turn_id === turnId))
    .slice(-24).map(item => ({
      id: item.id, phase: item.phase, status: item.status,
      content: (item.content || []).filter(part => part.type === 'output_text' && typeof part.text === 'string').map(part => part.text).join('\n').slice(0, 20000)
    })).filter(item => item.content);
}

export function failureDetails(session, turn) {
  const error = turn?.error || session.error;
  return {
    source: turn?.error ? 'OpenAI turn' : 'OpenAI session',
    code: typeof error?.code === 'string' ? error.code.slice(0, 120) : null,
    message: (typeof error === 'string' ? error : error?.message || 'The cloud request did not finish.').slice(0, 2000),
    sessionId: session.id || null, turnId: turn?.id || null
  };
}

export function visibleEvent(event) {
  const type = event.type;
  if (['agent.session.turn.output_text.delta', 'agent.session.turn.output_text.done'].includes(type)) {
    const replace = type.endsWith('.done'), text = replace ? event.text : event.delta;
    if (typeof text !== 'string' || typeof event.item_id !== 'string' || !Number.isInteger(event.content_index)) return null;
    return { kind: 'text', id: event.item_id, part: event.content_index, text: text.slice(0, 20000), replace };
  }
  if (type === 'agent.session.turn.item.done') {
    const message = assistantMessages(event.item ? [event.item] : [])[0];
    if (message) return { kind: 'message', ...message };
  }
  if (['agent.session.turn.completed', 'agent.session.turn.failed', 'agent.session.turn.cancelled', 'agent.session.failed', 'agent.session.environment.failed', 'error'].includes(type)) {
    return { kind: 'settle' };
  }
  if (type === 'agent.session.environment.connected') return { kind: 'status', text: 'The workspace is ready.' };
  if (type === 'agent.session.turn.in_progress') return { kind: 'status', text: 'The assistant is working on your message…' };
  return null;
}
