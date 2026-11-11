import { HttpError } from './security.js';

// One authenticated POST carries the request and the answer. A disconnect
// closes the upstream model stream; it never triggers another paid submission.
export function liveChat(action, signal, config) {
  const abort = new AbortController(), deadline = Date.now() + 85000;
  const stop = () => abort.abort(signal.reason);
  signal.addEventListener('abort', stop, { once: true });
  if (signal.aborted) stop();
  const timeout = setTimeout(() => abort.abort(new DOMException('Live response time limit reached', 'TimeoutError')), 85000), encoder = new TextEncoder();
  let closed = false, heartbeat;
  const body = new ReadableStream({
    async start(controller) {
      const emit = event => { if (!closed) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`)); };
      emit({ kind: 'connected' });
      heartbeat = setInterval(() => emit({ kind: 'keepalive' }), 10000);
      try {
        const result = await action({ emit, signal: abort.signal, deadline });
        emit({ kind: 'result', result });
      } catch (error) {
        const message = error instanceof HttpError ? error.message : 'The live connection could not finish. Your saved conversation remains available.';
        emit({ kind: 'error', message: message.replaceAll(config.apiKey || '\0', '[redacted]') });
      } finally {
        clearInterval(heartbeat); clearTimeout(timeout); signal.removeEventListener('abort', stop);
        if (!closed) { closed = true; controller.close(); }
      }
    },
    cancel() { closed = true; clearInterval(heartbeat); stop(); }
  });
  return new Response(body, { headers: { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-store, no-transform',
    'X-Content-Type-Options': 'nosniff', 'X-Robots-Tag': 'noindex', 'X-Accel-Buffering': 'no' } });
}
