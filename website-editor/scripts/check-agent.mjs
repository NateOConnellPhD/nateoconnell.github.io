// An explicitly invoked live check, not part of the test suite or application.
// Sends no website files, conversation history, GitHub credentials, or user data.
import { randomUUID } from 'node:crypto';
import { readEvents } from '../public/event-stream.js';

const key = process.env.OPENAI_API_KEY;
if (!key) {
  console.error('Set OPENAI_API_KEY to the same key used in Vercel. Do not paste it into chat.');
  process.exit(1);
}
const hosted = process.argv.includes('--hosted');
const authOnly = process.argv.includes('--auth-only');
const model = process.env.OPENAI_AGENT_MODEL || 'gpt-6-astra';
const root = 'https://api.openai.com/v1/agents';
const requestId = randomUUID(), deadline = AbortSignal.timeout(90000);
const headers = { Authorization: `Bearer ${key}`, 'OpenAI-Beta': 'agents=v1', 'Content-Type': 'application/json' };
const safe = value => String(value).replaceAll(key, '[redacted]').replace(/sk-[A-Za-z0-9_.-]+/g, '[redacted]');
const log = value => console.log(safe(typeof value === 'string' ? value : JSON.stringify(value)));
const validId = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,256}$/.test(value);
let sessionId, stream, settled = false, sawFailure = false, creationAttempted = false, creationRejected = false;
async function request(path, method = 'GET', body, signal = deadline, apiRoot = root) {
  const requestHeaders = apiRoot === root ? headers : { Authorization: headers.Authorization };
  const response = await fetch(apiRoot + path, { method, headers: requestHeaders, redirect: 'error', signal, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  log({ operation: `${method} ${new URL(apiRoot + path).pathname}`, status: response.status, requestId: response.headers.get('x-request-id') });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw Object.assign(new Error(`HTTP ${response.status}: ${detail.error?.code || ''} ${detail.error?.message || response.statusText}`), { status: response.status });
  }
  return response;
}
async function checkAuthentication() {
  log({ mode: 'read-only authentication check', modelRequests: 0 });
  const outcomes = {};
  for (const [name, apiRoot, path] of [['models', 'https://api.openai.com/v1', '/models'], ['agents', root, '/sessions?limit=1']]) {
    try {
      const response = await request(path, 'GET', undefined, AbortSignal.timeout(15000), apiRoot);
      // Only report access, never the account's model list or saved session data.
      await response.body?.cancel();
      outcomes[name] = response.status;
    } catch (error) {
      outcomes[name] = error.status || 'network error';
      log({ check: name, error: error.message });
    }
  }
  process.exitCode = Object.values(outcomes).every(status => typeof status === 'number' && status >= 200 && status < 300) ? 0 : 1;
  log({ access: outcomes, note: 'Models and Agents have separate permissions. This check does not test inference or session creation.' });
}
async function checkModel() {
  log({ model, environment: hosted ? 'minimal OpenAI-hosted sandbox' : 'no sandbox', timeoutSeconds: 90 });
  creationAttempted = true;
  // Conversation-only sessions require input at creation. Stream this same
  // request so a fast reply cannot finish before we subscribe to its events.
  stream = await request('/sessions', 'POST', {
    agent: { model, instructions: 'Reply with exactly the word connected. Do not use tools.', multi_agent: { enabled: false } },
    environment: { type: hosted ? 'openai_hosted' : 'none' },
    input: 'Reply with exactly the word connected.',
    stream: true,
    metadata: { editor_diagnostic: requestId }
  });
  for await (const event of readEvents(stream.body)) {
    const eventSessionId = event.session?.id || event.session_id;
    if (!sessionId && validId(eventSessionId)) {
      sessionId = eventSessionId; log({ sessionId });
    }
    if (event.type === 'agent.session.environment.connected') log('Sandbox connected.');
    if (event.type === 'agent.session.turn.output_text.done') log({ reply: event.text });
    if (event.type === 'error' || event.type.endsWith('.failed')) {
      sawFailure = true;
      log({ event: event.type, error: event.error || event.turn?.error || event.environment?.error || event.session?.error, turnId: event.turn?.id });
    }
    if (['agent.session.turn.completed', 'agent.session.turn.failed', 'agent.session.turn.cancelled', 'agent.session.failed', 'agent.session.environment.failed', 'error'].includes(event.type)) {
      settled = true;
      process.exitCode = event.type === 'agent.session.turn.completed' && !sawFailure ? 0 : 1;
      log({ outcome: process.exitCode ? 'failed' : 'completed' });
      break;
    }
  }
  if (!settled) throw new Error('The stream ended without a final outcome.');
}
try {
  await (authOnly ? checkAuthentication() : checkModel());
} catch (error) {
  process.exitCode = 1;
  creationRejected = creationAttempted && !sessionId && [400, 401, 403].includes(error.status);
  log({ error: error.message });
} finally {
  if (stream?.body && !stream.body.locked) await stream.body.cancel().catch(() => {});
  // Recover an uncertain creation before cleanup; never start a second model turn.
  if (!sessionId && creationAttempted && !creationRejected) {
    try {
      const query = new URLSearchParams({ limit: '10', 'metadata[editor_diagnostic]': requestId });
      const found = await (await request(`/sessions?${query}`, 'GET', undefined, AbortSignal.timeout(15000))).json();
      sessionId = found.data?.find(item => item.metadata?.editor_diagnostic === requestId)?.id;
    } catch { /* Report the unresolved identifier below. */ }
  }
  if (validId(sessionId)) {
    if (!settled) {
      try { await request(`/sessions/${sessionId}/events`, 'POST', { events: [{ type: 'agent.session.input.cancel' }] }, AbortSignal.timeout(10000)); }
      catch { /* Still attempt deletion if there was no active turn to cancel. */ }
    }
    try {
      await request(`/sessions/${sessionId}`, 'DELETE', undefined, AbortSignal.timeout(15000));
      log('Diagnostic session deleted.');
    } catch (error) {
      process.exitCode = 1;
      log({ cleanup: 'not confirmed; inspect this session in OpenAI', sessionId, error: error.message });
    }
  } else if (creationRejected) log({ cleanup: 'Session creation was rejected. No diagnostic session was created.' });
  else if (creationAttempted) log({ cleanup: 'No session ID was recovered. If creation timed out, check the OpenAI project.', diagnosticId: requestId });
}
