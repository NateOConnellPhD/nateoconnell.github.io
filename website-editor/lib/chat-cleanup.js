import { HttpError } from './security.js';
import { responseRequest } from './response-workspace.js';
import { agentRequest } from './hosted-agent.js';

const identifier = value => {
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(value || '')) throw new HttpError(400, 'Invalid saved cleanup identifier.');
  return value;
};

// Deletion only removes resources. Do not use the normal progress handler here:
// recovering an old submission through that handler can start another turn.
export async function cleanupDeletedChat(config, chat) {
  const run = chat.run;
  const sessions = new Set(run.sessionId ? [identifier(run.sessionId)] : []);
  const responses = [...new Set([...(run.responseIds || []), run.responseId].filter(Boolean))].map(identifier);
  const container = run.containerId ? identifier(run.containerId) : null;
  if (!sessions.size && !responses.length && !container && !run.lookupPending) return;
  if (!config.apiKey) throw new HttpError(503, 'The OpenAI key is needed to finish deleting this chat. Its saved conversation has been kept.');

  try {
    if (run.lookupPending && !sessions.size) {
      const key = identifier(run.key);
      const query = new URLSearchParams({ limit: '100', 'metadata[editor_chat]': chat.id, 'metadata[request]': key });
      const found = await agentRequest(config, `/sessions?${query}`);
      if (!Array.isArray(found.data) || found.has_more) throw new HttpError(502, 'OpenAI did not return a complete cleanup lookup.');
      for (const item of found.data) {
        if (item.metadata?.editor_chat === chat.id && item.metadata?.request === key) sessions.add(identifier(item.id));
      }
    }
    const remove = async action => {
      try { await action(); }
      catch (error) { if (error.status !== 404) throw error; }
    };
    const results = await Promise.allSettled([
      ...[...sessions].map(id => remove(() => agentRequest(config, `/sessions/${id}`, 'DELETE'))),
      ...responses.map(id => remove(() => responseRequest(config, `/responses/${id}`, 'DELETE'))),
      ...(container ? [remove(() => responseRequest(config, `/containers/${container}`, 'DELETE'))] : [])
    ]);
    const failed = results.find(result => result.status === 'rejected');
    if (failed) throw failed.reason;
  } catch (error) {
    throw new HttpError(502, `Remote cleanup could not finish. This chat has been kept; try Delete again. ${error.message}`);
  }
}
