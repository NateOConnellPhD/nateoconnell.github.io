import test from 'node:test';
import assert from 'node:assert/strict';
import { assistantMessages, visibleEvent } from '../lib/agent-output.js';
import { streamChat } from '../lib/chat-stream.js';
import { readEvents } from '../public/event-stream.js';
import { ChatOutput } from '../public/chat-output.js';
import { handle } from '../api/index.js';
import { configuration, seal, SESSION } from '../lib/security.js';

const encode = value => new TextEncoder().encode(`data: ${JSON.stringify(value)}\n\n`);
const message = (id, text, extra = {}) => ({ id, type: 'message', role: 'assistant', status: 'completed', phase: 'final_answer', turn_id: 'turn1', content: [{ type: 'output_text', text }], ...extra });

test('SSE handles split UTF-8, CRLF frames, comments and multiline data', async () => {
  const bytes = new TextEncoder().encode(': heartbeat\r\n\r\ndata: {"text":\r\ndata: "Nate’s research"}\r\n\r\ndata: [DONE]\n\n');
  const body = new ReadableStream({ start(c) { for (let i = 0; i < bytes.length; i += 3) c.enqueue(bytes.slice(i, i + 3)); c.close(); } });
  const events = []; for await (const event of readEvents(body)) events.push(event);
  assert.deepEqual(events, [{ text: 'Nate’s research' }]);
});

test('only assistant output is exposed, with no reasoning, tool payloads or earlier turns', () => {
  const items = [message('old', 'Earlier', { turn_id: 'other' }), { type: 'reasoning', summary: ['private reasoning'] }, { type: 'function_call', arguments: 'private payload' }, message('user', 'Private prompt', { role: 'user' }), message('reply', 'Which papers would you like to highlight?')];
  assert.deepEqual(assistantMessages(items, 'turn1').map(item => item.id), ['reply']);
  assert.equal(visibleEvent({ type: 'agent.session.turn.reasoning_summary_text.delta', delta: 'hidden' }), null);
  assert.equal(visibleEvent({ type: 'agent.session.turn.item.done', item: items[2] }), null);
  assert.equal(visibleEvent({ type: 'agent.session.turn.item.done', item: items[4] }).content, 'Which papers would you like to highlight?');
});

test('a reply reaches the browser before the turn ends, without forwarding credentials or unrelated events', async () => {
  let upstream;
  const source = new ReadableStream({ start(c) { upstream = c; } });
  const signal = new AbortController();
  const response = await streamChat({ apiKey: 'test-secret' }, { sessionId: 'sess_test', status: 'submitting' }, signal.signal, async (url, options) => {
    assert.ok(url.endsWith('/sessions/sess_test/events?stream=true'));
    assert.equal(options.headers.Authorization, 'Bearer test-secret');
    return new Response(source);
  });
  assert.equal(response.headers.get('content-type'), 'text/event-stream; charset=utf-8');
  const events = readEvents(response.body);
  assert.deepEqual((await events.next()).value, { kind: 'connected' });
  upstream.enqueue(encode({ type: 'agent.session.turn.reasoning_summary_text.delta', delta: 'hidden' }));
  upstream.enqueue(encode({ type: 'agent.session.turn.output_text.delta', item_id: 'msg1', content_index: 0, delta: 'I’ll look at the homepage.', secret: 'test-secret' }));
  const reply = (await events.next()).value;
  assert.equal(reply.text, 'I’ll look at the homepage.');
  assert.equal(JSON.stringify(reply).includes('secret'), false);
  upstream.enqueue(encode({ type: 'agent.session.turn.completed' }));
  assert.deepEqual((await events.next()).value, { kind: 'settle' });
  assert.equal((await events.next()).done, true);
});

test('closing the browser stream aborts its upstream connection without cancelling the task', async () => {
  let upstreamSignal;
  const response = await streamChat({ apiKey: 'test' }, { sessionId: 'sess_test', status: 'submitting' }, new AbortController().signal, async (url, options) => {
    upstreamSignal = options.signal;
    return new Response(new ReadableStream({ start(c) { options.signal.addEventListener('abort', () => c.error(new Error('closed')), { once: true }); } }));
  });
  await response.body.cancel();
  assert.equal(upstreamSignal.aborted, true);
});

test('finished conversations do not reopen cloud streams', async () => {
  const response = await streamChat({}, { sessionId: 'sess_test', status: 'failed' }, new AbortController().signal, () => { throw new Error('Must not call'); });
  assert.equal(response.status, 204);
});

test('snapshots and reconnect fragments do not duplicate text or replace the complete answer with a suffix', () => {
  const output = new ChatOutput();
  output.snapshot([{ id: 'first', content: 'Here are the papers on the homepage.', status: 'in_progress' }]);
  output.event({ kind: 'text', id: 'first', part: 0, text: 'on the homepage.', replace: false });
  assert.equal(output.messages()[0].content, 'Here are the papers on the homepage.');
  output.event({ kind: 'text', id: 'first', part: 0, text: 'Here are the papers on the homepage. Which should change?', replace: true });
  assert.equal(output.messages()[0].content, 'Here are the papers on the homepage. Which should change?');
  output.event({ kind: 'text', id: 'first', part: 0, text: 'duplicate suffix', replace: false });
  assert.equal(output.messages()[0].content.includes('duplicate'), false);
  output.event({ kind: 'message', id: 'first', content: 'Authoritative complete answer.' });
  assert.equal(output.messages()[0].content, 'Authoritative complete answer.');
});

test('recovered earlier messages appear before live messages', () => {
  const output = new ChatOutput();
  output.event({ kind: 'text', id: 'second', part: 0, text: 'Second', replace: false });
  output.snapshot([{ id: 'first', content: 'First' }, { id: 'second', content: 'Second' }]);
  assert.deepEqual(output.messages().map(item => item.id), ['first', 'second']);
});

test('the stream route rejects missing or wrong-account sessions before contacting either provider', async () => {
  const env = { APP_ORIGIN: 'https://editor.example', GITHUB_CLIENT_ID: 'client', GITHUB_CLIENT_SECRET: 'secret', ALLOWED_GITHUB_USER_ID: '1', SESSION_SECRET: 'ab'.repeat(32), DRAFT_REPOSITORY: 'NateOConnellPhD/editor-private' };
  const previous = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]]));
  const originalFetch = globalThis.fetch;
  try {
    Object.assign(process.env, env);
    globalThis.fetch = async () => { throw new Error('Unauthorized stream reached a provider'); };
    const url = 'https://editor.example/api/chat/events?id=a2345678-1234-4234-9234-123456789abc';
    assert.equal((await handle(new Request(url))).status, 401);
    const token = seal({ id: '2', token: 'private-token', csrf: 'test' }, 'session', configuration(env));
    assert.equal((await handle(new Request(url, { headers: { cookie: `${SESSION}=${token}` } }))).status, 401);
  } finally {
    globalThis.fetch = originalFetch;
    for (const [key, value] of Object.entries(previous)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; }
  }
});

test('unexpected server errors have a traceable reference without exposing private content or credentials', async () => {
  const env = { APP_ORIGIN: 'https://editor.example', GITHUB_CLIENT_ID: 'client', GITHUB_CLIENT_SECRET: 'secret', ALLOWED_GITHUB_USER_ID: '1', SESSION_SECRET: 'ab'.repeat(32), DRAFT_REPOSITORY: 'NateOConnellPhD/editor-private' };
  const previous = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]]));
  const originalFetch = globalThis.fetch, originalError = console.error, logs = [];
  try {
    Object.assign(process.env, env); console.error = (...args) => logs.push(args);
    globalThis.fetch = async url => {
      if (url.includes('/contents/')) return Response.json({ type: 'file', size: 20, encoding: 'base64', sha: 'sha', content: Buffer.from('private-content-not-json').toString('base64') });
      return Response.json({ private: true, fork: false, default_branch: 'main', owner: { login: 'NateOConnellPhD' } });
    };
    const token = seal({ id: '1', token: 'private-token', csrf: 'test' }, 'session', configuration(env));
    const response = await handle(new Request('https://editor.example/api/chat/events?id=a2345678-1234-4234-9234-123456789abc', { headers: { cookie: `${SESSION}=${token}` } }));
    assert.equal(response.status, 500);
    const payload = await response.json();
    assert.match(payload.error, /reference/);
    assert.ok(payload.error.includes(logs[0][1].reference));
    assert.equal(logs[0][1].kind, 'SyntaxError');
    assert.equal(/private-content|private-token|secret/.test(JSON.stringify([payload, logs])), false);
  } finally {
    globalThis.fetch = originalFetch; console.error = originalError;
    for (const [key, value] of Object.entries(previous)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; }
  }
});
