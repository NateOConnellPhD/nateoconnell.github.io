import test from 'node:test';
import assert from 'node:assert/strict';
import { startChat, pollChat, stopChat } from '../lib/repository-chat.js';
import { RepositoryTools } from '../lib/repository-tools.js';
import { saveChat, loadChat, websiteSnapshot } from '../lib/site-chat.js';
import { configuration, blobSha, SITE, HttpError } from '../lib/security.js';
import { liveChat } from '../lib/live-chat.js';
import { liveRequest } from '../public/live-request.js';

const config = { ...configuration({ APP_ORIGIN: 'https://editor.example', GITHUB_CLIENT_ID: 'client', GITHUB_CLIENT_SECRET: 'secret',
  ALLOWED_GITHUB_USER_ID: '1', SESSION_SECRET: 'ab'.repeat(32), DRAFT_REPOSITORY: 'NateOConnellPhD/private' }), apiKey: 'test-key' };
const id = 'a2345678-1234-4234-9234-123456789abc';
const message = text => ({ type: 'message', id: 'msg', role: 'assistant', phase: 'final_answer', content: [{ type: 'output_text', text }] });
const call = (name, args, id = 'call1') => ({ type: 'function_call', call_id: id, name, arguments: JSON.stringify(args) });
function store() {
  const files = new Map(), source = new Map([['index.html', 'Homepage selects featured research'],
    ['_research/one.md', '---\ntitle: One\nfeatured: true\npublished: true\n---\nAbstract'],
    ['assets/css/site.css', 'body { color: blue; }'], ['unrelated.js', 'large irrelevant file']]);
  const reads = [], commits = []; let version = 0;
  return { config: { ...config }, files, source, reads, commits,
    head: async repo => repo === SITE ? 'a'.repeat(40) : 'private-head-' + version,
    tree: async () => { reads.push('TREE'); return { entries: [...source].map(([path, content]) => ({ type: 'blob', mode: '100644', path, size: content.length, sha: blobSha(content) })) }; },
    blob: async (repo, sha) => { assert.equal(repo, SITE); const [path, content] = [...source].find(([, value]) => blobSha(value) === sha); reads.push(path); return { sha, buffer: Buffer.from(content) }; },
    read: async (repo, path) => { const text = (repo === SITE ? source : files).get(path); return text === undefined ? null : { sha: blobSha(text), buffer: Buffer.from(text) }; },
    readJson: async (repo, path, ref, fallback) => files.has(path) ? JSON.parse(files.get(path)) : structuredClone(fallback),
    writePrivate: async (path, content, sha) => { if (blobSha(files.get(path) || '') !== sha) throw new HttpError(409, 'CAS conflict'); files.set(path, content); version++; },
    commit: async (repo, head, changes) => { assert.equal(repo, config.drafts); if (head !== 'private-head-' + version) throw new HttpError(409, 'Commit conflict'); version++; commits.push(changes);
      for (const file of changes) { if (file.content === null) files.delete(file.path); else files.set(file.path, file.content); } return 'private-commit'; }
  };
}
const initial = fake => saveChat(fake, { id, title: 'New chat', messages: [], changes: [] }, null);
function provider(outputs, usage = { input_tokens: 100, input_tokens_details: { cached_tokens: 80 }, output_tokens: 10 }) {
  const requests = []; let created = 0;
  return { requests, fetch: async (url, options) => {
    requests.push({ url, method: options.method, body: options.body && JSON.parse(options.body) });
    assert.ok(!url.includes('/containers'), 'ordinary chat must never allocate a container');
    if (options.method === 'POST' && url.endsWith('/responses')) {
      const response = { id: 'resp_' + (++created), status: 'in_progress' };
      return new Response('data: ' + JSON.stringify({ type: 'response.created', response }) + '\n\n');
    }
    if (options.method === 'GET') {
      const number = Number(url.match(/resp_(\d+)/)[1]);
      return Response.json({ id: 'resp_' + number, status: 'completed', output: outputs[number - 1], usage });
    }
    return Response.json({});
  } };
}

function foregroundProvider(outputs, pause) {
  const requests = []; let created = 0;
  return { requests, fetch: async (url, options) => {
    const body = options.body && JSON.parse(options.body);
    requests.push({ url, method: options.method, body });
    if (options.method === 'DELETE') return Response.json({});
    assert.equal(url, 'https://api.openai.com/v1/responses');
    assert.equal(options.method, 'POST');
    assert.equal(body.background, false);
    assert.equal(body.stream, true);
    const number = created++, id = 'resp_' + number, output = outputs[number];
    const encoder = new TextEncoder();
    return new Response(new ReadableStream({
      async start(controller) {
        let closed = false;
        const abort = () => { if (!closed) { closed = true; controller.error(new Error('Disconnected')); } };
        options.signal.addEventListener('abort', abort, { once: true });
        const emit = value => { if (!closed) controller.enqueue(encoder.encode('data: ' + JSON.stringify(value) + '\n\n')); };
        emit({ type: 'response.created', response: { id, status: 'in_progress' } });
        if (output[0]?.type === 'message') emit({ type: 'response.output_text.delta', item_id: 'msg', content_index: 0, delta: 'Connected' });
        await pause?.();
        emit({ type: 'response.completed', response: { id, status: 'completed', output, usage: { input_tokens: 20, output_tokens: 4 } } });
        options.signal.removeEventListener('abort', abort);
        if (!closed) { closed = true; controller.close(); }
      }
    }), { headers: { 'Content-Type': 'text/event-stream' } });
  } };
}

test('a short reply streams through its original POST before completion, without polling or a workspace', async () => {
  const fake = store(), first = await initial(fake);
  let complete, firstToken;
  const gate = new Promise(resolve => { complete = resolve; });
  const received = new Promise(resolve => { firstToken = resolve; });
  const remote = foregroundProvider([[message('Connected — what would you like to change?')]], () => gate);
  const originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    const signal = new AbortController().signal;
    const response = liveChat(flow => startChat(fake, config, { id, revision: first.revision, prompt: 'testing' }, flow), signal, config);
    const result = liveRequest('chat/send', { prompt: 'testing' }, 'csrf', event => { if (event.kind === 'text') firstToken(event.text); }, signal,
      async (url, options) => { assert.equal(options.headers.Accept, 'text/event-stream'); return response; });
    assert.equal(await received, 'Connected');
    assert.equal((await loadChat(fake, id)).chat.run.status, 'in_progress');
    await Promise.all([pollChat(fake, config, id), pollChat(fake, config, id)]);
    assert.equal(remote.requests.length, 1, 'another tab cannot poll/submit into a live turn');
    assert.deepEqual(fake.reads, []);
    complete();
    const saved = await result;
    assert.equal(saved.chat.run.status, 'completed');
    assert.equal(saved.chat.messages.at(-1).content, 'Connected — what would you like to change?');
    assert.equal(saved.chat.usage.model_requests, 1);
    assert.equal(saved.chat.usage.containers, 0);
    assert.ok(remote.requests.every(request => request.method !== 'GET'));
  } finally { complete(); globalThis.fetch = originalFetch; }
});

test('foreground file tools checkpoint their output and continue with one new streamed call', async () => {
  const fake = store(), first = await initial(fake), events = [];
  const flow = { signal: new AbortController().signal, deadline: Date.now() + 85000, emit: event => events.push(event.kind) };
  const remote = foregroundProvider([[call('read_files', { paths: ['index.html'] })], [message('The homepage uses featured research.')]]);
  const originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    let saved = await startChat(fake, config, { id, revision: first.revision, prompt: 'Read the homepage.' }, flow);
    assert.equal(saved.chat.run.stage, 'ready');
    assert.deepEqual(fake.reads, ['TREE', 'index.html']);
    saved = await pollChat(fake, config, id, flow);
    assert.equal(saved.chat.run.status, 'completed');
    const calls = remote.requests.filter(request => request.method === 'POST');
    assert.equal(calls.length, 2);
    assert.equal(calls[1].body.previous_response_id, 'resp_0');
    assert.equal(JSON.parse(calls[1].body.input[0].output).files[0].path, 'index.html');
    assert.ok(events.includes('text'));
  } finally { globalThis.fetch = originalFetch; }
});

test('disconnecting a foreground stream preserves the conversation and never repeats creation', async () => {
  const fake = store(), first = await initial(fake), abort = new AbortController();
  let release, received;
  const gate = new Promise(resolve => { release = resolve; });
  const token = new Promise(resolve => { received = resolve; });
  const remote = foregroundProvider([[message('Unfinished')]], () => gate);
  const originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    const result = startChat(fake, config, { id, revision: first.revision, prompt: 'testing' }, {
      signal: abort.signal, deadline: Date.now() + 85000, emit: event => { if (event.kind === 'text') received(); }
    });
    await token; abort.abort();
    const saved = await result;
    assert.equal(saved.chat.run.status, 'cancelled');
    assert.equal(saved.chat.messages[0].content, 'testing');
    assert.equal(saved.chat.run.cleanupPending, false);
    assert.equal(remote.requests.filter(request => request.method === 'POST').length, 1);
    assert.ok(remote.requests.every(request => !request.url.includes('/cancel')));
  } finally { release(); globalThis.fetch = originalFetch; }
});

test('a lost foreground checkpoint acknowledgement does not break the live reply', async () => {
  const fake = store(), first = await initial(fake), write = fake.writePrivate;
  let lost = false;
  fake.writePrivate = async (...args) => { await write(...args); if (!lost && JSON.parse(args[1]).run?.stage === 'waiting') { lost = true; throw new Error('Lost acknowledgement'); } };
  const remote = foregroundProvider([[message('Connected')]]);
  const originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    const saved = await startChat(fake, config, { id, revision: first.revision, prompt: 'testing' }, {
      signal: new AbortController().signal, deadline: Date.now() + 85000, emit() {}
    });
    assert.equal(lost, true);
    assert.equal(saved.chat.run.status, 'completed');
    assert.equal(saved.chat.messages.at(-1).content, 'Connected');
    assert.equal(remote.requests.filter(request => request.method === 'POST').length, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test('a broken live stream is reported without retrying the paid request', async () => {
  let calls = 0;
  await assert.rejects(liveRequest('chat/send', {}, 'csrf', () => {}, new AbortController().signal, async () => {
    calls++; return new Response('data: {"kind":"connected"}\n\n', { headers: { 'Content-Type': 'text/event-stream' } });
  }), /no paid request will be repeated/);
  assert.equal(calls, 1);
});

test('a first message creates its conversation atomically, without an empty-chat commit', async () => {
  const fake = store(), remote = foregroundProvider([[message('Connected')]]);
  const originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    const saved = await startChat(fake, config, { id, revision: null, prompt: 'testing' }, {
      signal: new AbortController().signal, deadline: Date.now() + 85000, emit() {}
    });
    assert.equal(saved.chat.run.status, 'completed');
    const initialChat = JSON.parse(fake.commits[0].find(file => file.path === `chats/${id}.json`).content);
    assert.equal(initialChat.messages[0].content, 'testing');
    assert.ok(fake.commits[0].some(file => file.path === 'usage.json'));
    await assert.rejects(startChat(fake, config, { id, revision: null, prompt: 'overwrite?' }), /changed/);
    assert.equal(remote.requests.filter(request => request.method === 'POST').length, 1);
    assert.equal((await loadChat(fake, id)).chat.messages.at(-1).content, 'Connected');
  } finally { globalThis.fetch = originalFetch; }
});

test('an expired foreground owner recovers a completed response without another model call', async () => {
  const fake = store(), first = await initial(fake), remote = provider([[message('Recovered reply')]]);
  const originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    const saved = await startChat(fake, config, { id, revision: first.revision, prompt: 'testing' });
    saved.chat.run.transport = 'foreground'; saved.chat.run.leaseUntil = Date.now() - 1;
    await saveChat(fake, saved.chat, saved.revision);
    const recovered = await pollChat(fake, config, id);
    assert.equal(recovered.chat.run.status, 'completed');
    assert.equal(recovered.chat.messages.at(-1).content, 'Recovered reply');
    assert.equal(remote.requests.filter(request => request.method === 'POST').length, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test('a homepage question starts without source hydration, then reads only requested files and records usage', async () => {
  const fake = store(), first = await initial(fake);
  const remote = provider([[call('read_files', { paths: ['index.html', '_research/one.md'] })], [message('One is currently highlighted.')]]);
  const originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    let saved = await startChat(fake, config, { id, revision: first.revision, prompt: 'Which papers are highlighted?' });
    assert.deepEqual(fake.reads, []);
    assert.equal(saved.chat.run.backend, 'repository');
    saved = await pollChat(fake, config, id);
    assert.deepEqual(fake.reads.sort(), ['TREE', '_research/one.md', 'index.html'].sort());
    const requests = remote.requests.filter(item => item.method === 'POST');
    assert.equal(requests[1].body.previous_response_id, 'resp_1');
    assert.equal(JSON.parse(requests[1].body.input[0].output).files[1].sha, blobSha(fake.source.get('_research/one.md')));
    saved = await pollChat(fake, config, id);
    assert.equal(saved.chat.run.status, 'completed');
    assert.equal(saved.chat.messages.at(-1).content, 'One is currently highlighted.');
    assert.deepEqual(saved.chat.changes, []);
    assert.equal(saved.chat.usage.input_tokens, 200);
    assert.equal(saved.chat.usage.cached_input_tokens, 160);
    assert.equal(saved.chat.usage.output_tokens, 20);
    assert.equal(saved.chat.usage.model_requests, 2);
    assert.equal(saved.chat.usage.containers, 0);
    assert.equal(saved.chat.run.cleanupPending, false);
    await pollChat(fake, config, id);
    assert.equal((await loadChat(fake, id)).chat.usage.input_tokens, 200);
  } finally { globalThis.fetch = originalFetch; }
});

test('a direct edit preserves other proposals and a follow-up reads the private version', async () => {
  const fake = store(), chat = { id, messages: [], changes: [] };
  const repo = new RepositoryTools(fake, chat, 'a'.repeat(40));
  await repo.call('write_file', { path: 'new-page.html', expected_sha: null, content: '<h1>New</h1>', reason: 'Requested page' });
  const current = await repo.call('read_files', { paths: ['assets/css/site.css'] });
  await repo.call('edit_file', { path: 'assets/css/site.css', expected_sha: current.files[0].sha, replacements: [{ old_text: 'blue', new_text: 'navy' }] });
  assert.equal((await repo.read('assets/css/site.css')).content, 'body { color: navy; }');
  assert.equal(chat.changes.length, 2);
  assert.equal(fake.source.get('assets/css/site.css'), 'body { color: blue; }');
  await assert.rejects(repo.call('edit_file', { path: 'assets/css/site.css', expected_sha: current.files[0].sha, replacements: [{ old_text: 'navy', new_text: 'red' }] }), /changed/);
  await assert.rejects(repo.call('read_files', { paths: ['context_not_for_upload/paper.pdf'] }), /outside/);
  await assert.rejects(repo.call('write_file', { path: 'bad.json', expected_sha: null, content: '{bad', reason: 'invalid' }), /Invalid JSON/);
  assert.equal(chat.changes.length, 2);
});

test('manual file editing downloads only the paths being changed', async () => {
  const fake = store();
  const snapshot = await websiteSnapshot(fake, [], null, ['assets/css/site.css', 'new.html']);
  assert.deepEqual(fake.reads, ['TREE', 'assets/css/site.css']);
  assert.equal(snapshot.files.size, 1);
  assert.ok(snapshot.occupied.has('index.html'));
  assert.equal(snapshot.binaries.has('index.html'), false);
  await assert.rejects(websiteSnapshot(fake, [], null, ['../private']), /outside/);
});

test('deleting a large binary uses its revision without downloading or executing it', async () => {
  const fake = store(), sha = 'b'.repeat(40), chat = { messages: [], changes: [] };
  fake.tree = async () => ({ entries: [{ path: 'assets/files/old-cv.pdf', type: 'blob', mode: '100644', size: 4000000, sha }] });
  fake.blob = async () => assert.fail('Binary deletion needs no file download');
  const repo = new RepositoryTools(fake, chat, 'a'.repeat(40));
  await repo.call('write_file', { path: 'assets/files/old-cv.pdf', expected_sha: sha, content: null, reason: 'Requested deletion' });
  assert.equal(chat.changes[0].after, null);
  assert.equal(chat.changes[0].beforeSha, sha);
  assert.equal(chat.changes[0].binaryBefore, true);
});

test('concurrent polling advances one response only once', async () => {
  const fake = store(), first = await initial(fake);
  const remote = provider([[call('read_files', { paths: ['index.html'] })], [message('Done')]]);
  const originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    await startChat(fake, config, { id, revision: first.revision, prompt: 'Read the homepage.' });
    await Promise.all([pollChat(fake, config, id), pollChat(fake, config, id)]);
    assert.equal(remote.requests.filter(item => item.method === 'POST' && item.url.endsWith('/responses')).length, 2);
  } finally { globalThis.fetch = originalFetch; }
});

test('a lost creation reply never automatically repeats a paid request', async () => {
  const fake = store(), first = await initial(fake), originalFetch = globalThis.fetch; let attempts = 0;
  globalThis.fetch = async () => { attempts++; throw new Error('network disconnected'); };
  try {
    const saved = await startChat(fake, config, { id, revision: first.revision, prompt: 'Hello' });
    assert.equal(saved.chat.run.status, 'failed');
    assert.equal(attempts, 1);
    await pollChat(fake, config, id); assert.equal(attempts, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test('a lost Git checkpoint reply does not cancel or duplicate a response already saved', async () => {
  const fake = store(), first = await initial(fake), remote = provider([[message('Hello')]]);
  const originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  const write = fake.writePrivate; let lost = false;
  fake.writePrivate = async (...args) => { await write(...args); if (!lost && JSON.parse(args[1]).run?.responseId) { lost = true; throw new Error('Git acknowledgement lost'); } };
  try {
    const saved = await startChat(fake, config, { id, revision: first.revision, prompt: 'Hello' });
    assert.equal(saved.chat.run.status, 'in_progress');
    assert.equal(remote.requests.length, 1);
    assert.equal((await pollChat(fake, config, id)).chat.run.status, 'completed');
    assert.equal(remote.requests.some(item => item.url.endsWith('/cancel')), false);
  } finally { globalThis.fetch = originalFetch; }
});

test('the model-step limit stops a tool loop before another paid call', async () => {
  const fake = store(), first = await initial(fake), remote = provider([[call('list_files', { prefix: '', offset: 0 })]]);
  const originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    await startChat(fake, { ...config, chatSteps: 1 }, { id, revision: first.revision, prompt: 'Read files' });
    const saved = await pollChat(fake, { ...config, chatSteps: 1 }, id);
    assert.equal(saved.chat.run.status, 'failed');
    assert.match(saved.chat.run.error, /limit/);
    assert.equal(remote.requests.filter(item => item.method === 'POST').length, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test('stop saves cancellation and does not start another model call', async () => {
  const fake = store(), first = await initial(fake), remote = provider([]);
  const originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    await startChat(fake, config, { id, revision: first.revision, prompt: 'Hello' });
    const stopped = await stopChat(fake, config, id);
    assert.equal(stopped.chat.run.status, 'cancelled');
    await pollChat(fake, config, id);
    assert.equal(remote.requests.filter(item => item.method === 'POST' && item.url.endsWith('/responses')).length, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test('the daily allowance is atomic with the message, and simultaneous sends submit once', async () => {
  const fake = store(), first = await initial(fake), remote = provider([]);
  const originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    const results = await Promise.allSettled([1, 2].map(() => startChat(fake, config, { id, revision: first.revision, prompt: 'Hello' })));
    assert.equal(results.filter(item => item.status === 'fulfilled').length, 1);
    assert.equal(remote.requests.length, 1);
    const reservations = fake.commits.filter(commit => commit.some(file => file.path === 'usage.json'));
    assert.equal(reservations.length, 1);
    assert.ok(reservations[0].some(file => file.path === `chats/${id}.json`));
    assert.equal(JSON.parse(fake.files.get('usage.json')).count, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test('an exhausted daily allowance starts no paid request and saves no message', async () => {
  const fake = store(), first = await initial(fake);
  fake.files.set('usage.json', JSON.stringify({ day: new Date().toISOString().slice(0, 10), count: config.daily }));
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => assert.fail('No model request allowed');
  try {
    await assert.rejects(startChat(fake, config, { id, revision: first.revision, prompt: 'Hello' }), /daily/);
    assert.equal((await loadChat(fake, id)).chat.messages.length, 0);
  } finally { globalThis.fetch = originalFetch; }
});

test('stopping while creation is in flight retains and cancels the eventual response ID', async () => {
  const fake = store(), first = await initial(fake), remote = provider([]);
  let release, entered;
  const waiting = new Promise(resolve => { release = resolve; }), submitted = new Promise(resolve => { entered = resolve; });
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => { if (url.endsWith('/responses') && options.method === 'POST') { entered(); await waiting; } return remote.fetch(url, options); };
  try {
    const running = startChat(fake, config, { id, revision: first.revision, prompt: 'Hello' });
    await submitted;
    assert.equal((await stopChat(fake, config, id)).chat.run.status, 'cancelling');
    release(); await running;
    const saved = await loadChat(fake, id);
    assert.equal(saved.chat.run.status, 'cancelled');
    assert.equal(saved.chat.run.responseId, 'resp_1');
    assert.ok(remote.requests.some(item => item.url.endsWith('/resp_1/cancel')));
    assert.ok(remote.requests.some(item => item.method === 'DELETE' && item.url.endsWith('/resp_1')));
    assert.equal(remote.requests.filter(item => item.method === 'POST' && item.url.endsWith('/responses')).length, 1);
  } finally { release(); globalThis.fetch = originalFetch; }
});

test('a transient stop failure remains recoverable without another model request', async () => {
  const fake = store(), first = await initial(fake), remote = provider([]);
  let fail = true; const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => url.endsWith('/cancel') && fail ? Response.json({}, { status: 503 }) : remote.fetch(url, options);
  try {
    await startChat(fake, config, { id, revision: first.revision, prompt: 'Hello' });
    assert.equal((await stopChat(fake, config, id)).chat.run.status, 'cancelling');
    fail = false;
    assert.equal((await pollChat(fake, config, id)).chat.run.status, 'cancelled');
    assert.equal(remote.requests.filter(item => item.method === 'POST' && item.url.endsWith('/responses')).length, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test('large tool batches resume from saved cursors without replaying completed file reads', async () => {
  const fake = store(), first = await initial(fake);
  const calls = Array.from({ length: 5 }, (_, index) => call('read_files', { paths: ['index.html'] }, 'call' + index));
  const remote = provider([calls, [message('Done')]]), originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    await startChat(fake, config, { id, revision: first.revision, prompt: 'Review' });
    let saved = await pollChat(fake, config, id);
    assert.equal(saved.chat.run.stage, 'tools'); assert.equal(saved.chat.run.toolIndex, 4);
    assert.equal(remote.requests.filter(item => item.method === 'POST').length, 1);
    fake.reads.length = 0;
    saved = await pollChat(fake, config, id);
    assert.equal(saved.chat.run.stage, 'waiting');
    assert.deepEqual(fake.reads, ['TREE', 'index.html']);
    const next = remote.requests.filter(item => item.method === 'POST').at(-1);
    assert.equal(next.body.input.length, 5);
  } finally { globalThis.fetch = originalFetch; }
});

test('missing provider usage conservatively consumes the assigned output allowance', async () => {
  const fake = store(), first = await initial(fake), remote = provider([[call('list_files', { prefix: '', offset: 0 })]], null);
  const limited = { ...config, chatOutputTokens: 1024 }, originalFetch = globalThis.fetch; globalThis.fetch = remote.fetch;
  try {
    await startChat(fake, limited, { id, revision: first.revision, prompt: 'Review' });
    const saved = await pollChat(fake, limited, id);
    assert.equal(saved.chat.run.status, 'failed');
    assert.equal(saved.chat.run.outputBudgetUsed, 1024);
    assert.equal(saved.chat.usage.reported_responses, 0);
    assert.equal(remote.requests.filter(item => item.method === 'POST').length, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test('execution starts only on request and resumes a saved handoff with edits and PDF context intact', async () => {
  const fake = store(), first = await initial(fake), remote = provider([[call('write_file', { path: 'new.html', expected_sha: null, content: '<h1>New</h1>', reason: 'Requested' }), call('request_execution', { task: 'Build a preview of the new page.' }, 'execute')]]);
  const originalFetch = globalThis.fetch, requests = []; let payload, execution, interrupted = false, executionAckLost = false;
  const write = fake.writePrivate;
  fake.writePrivate = async (...args) => {
    await write(...args);
    if (JSON.parse(args[1]).run?.stage === 'ready' && !interrupted) { interrupted = true; throw new Error('connection closed after save'); }
    if (JSON.parse(args[1]).run?.responseId === 'resp_exec' && !executionAckLost) { executionAckLost = true; throw new Error('execution checkpoint acknowledgement lost'); }
  };
  globalThis.fetch = async (url, options) => {
    requests.push({ url, method: options.method });
    if (url.endsWith('/containers') && options.method === 'POST') return Response.json({ id: 'cntr_exec' });
    if (url.endsWith('/files')) {
      const file = options.body.get('file');
      if (file.name === 'project-input.json') payload = JSON.parse(await file.text());
      return Response.json({ path: '/mnt/data/' + file.name });
    }
    if (options.method === 'DELETE') return Response.json({});
    if (url.endsWith('/responses') && JSON.parse(options.body).tools[0].type === 'shell') {
      execution = JSON.parse(options.body);
      return new Response('data: {"type":"response.created","response":{"id":"resp_exec"}}\n\n');
    }
    if (url.endsWith('/responses/resp_exec')) return Response.json({ id: 'resp_exec', status: 'completed', output: [message('Execution complete.')], usage: { input_tokens: 50, output_tokens: 25 } });
    return remote.fetch(url, options);
  };
  try {
    await startChat(fake, config, { id, revision: first.revision, prompt: 'Add a page and build a preview.', attachment: { base64: Buffer.from('%PDF-reference').toString('base64') } });
    assert.equal(requests.some(item => item.url.includes('/containers')), false);
    await assert.rejects(pollChat(fake, config, id), /connection closed/);
    assert.equal((await loadChat(fake, id)).chat.run.executionTask, 'Build a preview of the new page.');
    let saved = await pollChat(fake, config, id);
    assert.equal(saved.chat.run.backend, 'responses');
    assert.equal(requests.some(item => item.method === 'DELETE'), false);
    assert.equal(execution.previous_response_id, 'resp_1');
    assert.equal(execution.input[1].call_id, 'execute');
    assert.equal(execution.max_output_tokens, config.chatOutputTokens - 10);
    assert.equal(payload.pending[0].after, '<h1>New</h1>');
    assert.equal(payload.working, undefined);
    assert.ok(remote.requests[0].body.input[0].content.some(item => item.type === 'input_file'));
    saved = await pollChat(fake, config, id);
    assert.equal(saved.chat.usage.model_requests, 2); assert.equal(saved.chat.usage.containers, 1);
    assert.equal(saved.chat.changes[0].path, 'new.html');
    assert.equal(saved.chat.messages.length, 2);
    for (const suffix of ['/responses/resp_1', '/responses/resp_exec', '/containers/cntr_exec']) assert.ok(requests.some(item => item.method === 'DELETE' && item.url.endsWith(suffix)));
  } finally { globalThis.fetch = originalFetch; }
});
