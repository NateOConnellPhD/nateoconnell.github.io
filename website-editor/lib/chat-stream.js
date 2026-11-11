import { HttpError } from './security.js';
import { visibleEvent } from './agent-output.js';
import { readEvents } from '../public/event-stream.js';

export async function streamChat(config, run, signal, transport = fetch) {
  if (!run?.sessionId || ['completed', 'failed', 'cancelled'].includes(run.status)) return new Response(null, { status: 204 });
  if (!/^[a-zA-Z0-9_-]{1,256}$/.test(run.sessionId)) throw new HttpError(400, 'Invalid remote workspace identifier.');
  const abort = new AbortController();
  // Reconnect periodically, within the Vercel function's duration limit.
  const deadline = setTimeout(() => abort.abort(), 55000);
  const stop = () => abort.abort();
  signal.addEventListener('abort', stop, { once: true });
  const cleanup = () => { clearTimeout(deadline); signal.removeEventListener('abort', stop); abort.abort(); };
  let response;
  try {
    response = await transport(`https://api.openai.com/v1/agents/sessions/${run.sessionId}/events?stream=true`, {
      signal: AbortSignal.any([signal, abort.signal]), redirect: 'error',
      headers: { Authorization: `Bearer ${config.apiKey}`, 'OpenAI-Beta': 'agents=v1', Accept: 'text/event-stream' }
    });
    if (!response.ok || !response.body) throw new Error('Stream unavailable');
  } catch { cleanup(); throw new HttpError(502, 'Live replies are temporarily unavailable. The saved conversation can still be checked.'); }
  const encoder = new TextEncoder();
  let cancelled = false;
  const body = new ReadableStream({
    async start(controller) {
      const send = value => { if (!cancelled) controller.enqueue(encoder.encode(`data: ${JSON.stringify(value)}\n\n`)); };
      send({ kind: 'connected' });
      try {
        for await (const event of readEvents(response.body)) {
          const visible = visibleEvent(event);
          if (visible) send(visible);
          if (visible?.kind === 'settle') break;
        }
      } catch { /* The browser recovers missing messages from saved session items. */ }
      finally { cleanup(); if (!cancelled) controller.close(); }
    },
    cancel() { cancelled = true; cleanup(); }
  });
  return new Response(body, { headers: { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-store, no-transform', 'X-Content-Type-Options': 'nosniff', 'X-Robots-Tag': 'noindex' } });
}
