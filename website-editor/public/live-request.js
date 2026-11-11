import { readEvents } from './event-stream.js';

export async function liveRequest(route, data, csrf, onEvent, signal, transport = fetch) {
  const response = await transport(`/api/${route}`, { method: 'POST', credentials: 'same-origin', cache: 'no-store',
    signal: AbortSignal.any([signal, AbortSignal.timeout(110000)]),
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', 'X-CSRF-Token': csrf }, body: JSON.stringify(data) });
  if (!response.headers.get('content-type')?.includes('text/event-stream')) {
    // Safe during a deployment transition; never resend a request to negotiate.
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'The request could not be completed.');
    return result;
  }
  let result;
  for await (const event of readEvents(response.body)) {
    if (event.kind === 'error') throw new Error(event.message);
    if (event.kind === 'result') result = event.result;
    else onEvent(event);
  }
  if (!result) throw new Error('The live connection ended. Checking the saved conversation; no paid request will be repeated.');
  return result;
}
