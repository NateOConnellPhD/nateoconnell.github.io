import test from 'node:test';
import assert from 'node:assert/strict';
import { startChat, pollChat, stopChat } from '../lib/repository-chat.js';
import { RepositoryTools } from '../lib/repository-tools.js';
import { saveChat, loadChat, websiteSnapshot } from '../lib/site-chat.js';
import { configuration, blobSha, SITE, HttpError } from '../lib/security.js';

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
