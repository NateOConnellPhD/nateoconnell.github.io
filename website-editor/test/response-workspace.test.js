import test from 'node:test';
import assert from 'node:assert/strict';
import { startWorkspace, pollWorkspace, cancelWorkspace, responseRequest } from '../lib/response-workspace.js';
import { saveChat, applySiteProposal, websiteSnapshot } from '../lib/site-chat.js';
import { configuration, blobSha, SITE } from '../lib/security.js';

const env = { APP_ORIGIN: 'https://editor.example', GITHUB_CLIENT_ID: 'client', GITHUB_CLIENT_SECRET: 'secret', ALLOWED_GITHUB_USER_ID: '1', SESSION_SECRET: 'ab'.repeat(32), DRAFT_REPOSITORY: 'NateOConnellPhD/editor-private' };
const config = { ...configuration(env), apiKey: 'fake-api-key' };
const id = 'a2345678-1234-4234-9234-123456789abc';
const root = '/mnt/data/editor-workspace';
const active = { backend: 'responses', responseId: 'resp_test', containerId: 'cntr_test', requestId: 'req_test', head: 'public-head', key: 'key', started: Date.now(), status: 'in_progress' };
const reply = text => ({ type: 'message', id: 'msg_test', role: 'assistant', phase: 'final_answer', status: 'completed', content: [{ type: 'output_text', text }] });
function store() {
  const files = new Map(), publicFiles = new Map([['index.html', '<h1>Nate</h1>']]);
  return { config, files, publicFiles,
    head: async repo => repo === SITE ? 'public-head' : 'private-head',
    tree: async () => ({ entries: [...publicFiles].map(([path, content]) => ({ path, sha: blobSha(content), type: 'blob', mode: '100644', size: content.length })) }),
    read: async (repo, path) => { const content = (repo === SITE ? publicFiles : files).get(path); return content === undefined ? null : { sha: blobSha(content), buffer: Buffer.from(content) }; },
    readJson: async (repo, path, ref, fallback) => files.has(path) ? JSON.parse(files.get(path)) : structuredClone(fallback),
    commit: async (repo, head, changes) => { assert.equal(repo, config.drafts); for (const change of changes) files.set(change.path, change.content); return 'private-commit'; }
  };
}
const savedChat = fake => JSON.parse(fake.files.get(`chats/${id}.json`));
const initial = (fake, extra = {}) => saveChat(fake, { id, title: 'Conversation', messages: [], changes: [], ...extra }, null);
async function pending(fake) { return applySiteProposal([], { message: 'Credential', edits: [{ path: 'index.html', content: '<h1>Nate, PhD</h1>', reason: 'Credential' }] }, await websiteSnapshot(fake)); }
async function mocked(handler, operation) {
  const original = globalThis.fetch; globalThis.fetch = handler;
  try { return await operation(); } finally { globalThis.fetch = original; }
}

test('new chats use background Responses with hosted shell, private source and follow-up context', async () => {
  const fake = store(), changes = await pending(fake);
  const loaded = await initial(fake, { changes, messages: [{ role: 'user', content: 'What can you edit?' }, { role: 'assistant', content: 'The whole website.' }] });
  const calls = []; let uploaded, submitted, streamClosed = false;
  await mocked(async (url, options) => {
    calls.push(url); assert.ok(!url.includes('/agents/'));
    if (url.endsWith('/containers')) {
      assert.deepEqual(JSON.parse(options.body).network_policy, { type: 'disabled' });
      return Response.json({ id: 'cntr_test' });
    }
    if (url.endsWith('/files')) {
      assert.equal(savedChat(fake).run.containerId, 'cntr_test');
      const file = options.body.get('file');
      if (file.name === 'project-input.json') uploaded = JSON.parse(await file.text());
      return Response.json({ id: 'cfile_test', path: '/mnt/data/upload-' + file.name });
    }
    assert.ok(url.endsWith('/responses'));
    submitted = JSON.parse(options.body);
    return new Response(new ReadableStream({ start(c) {
      c.enqueue(new TextEncoder().encode('data: {"type":"response.created","response":{"id":"resp_test"}}\n\n'));
    }, cancel() { streamClosed = true; } }), { headers: { 'x-request-id': 'req_created' } });
  }, async () => {
    const result = await startWorkspace(fake, config, { id, revision: loaded.revision, prompt: 'Add a teaching page.' });
    assert.equal(result.chat.run.responseId, 'resp_test'); assert.equal(result.chat.run.requestId, 'req_created');
    assert.equal(result.chat.run.status, 'in_progress'); assert.equal(streamClosed, true);
  });
  assert.equal(calls.filter(url => url.endsWith('/responses')).length, 1);
  assert.equal(uploaded.original['index.html'], '<h1>Nate</h1>'); assert.equal(uploaded.working, undefined); assert.deepEqual(uploaded.pending, changes);
  assert.equal(submitted.model, 'gpt-6-astra'); assert.equal(submitted.background, true); assert.equal(submitted.stream, true); assert.equal(submitted.store, true);
  assert.deepEqual(submitted.tools[0], { type: 'shell', environment: { type: 'container_reference', container_id: 'cntr_test' } });
  assert.equal(submitted.input[1].content, 'The whole website.');
  assert.ok(submitted.instructions.includes(`python ${root}/workspace.py export ${root}`));
  assert.ok(!submitted.instructions.includes(`${root}/mnt/data/`));
  assert.ok(!JSON.stringify([uploaded, submitted]).includes('fake-api-key'));
});

test('ordinary conversation completes without shell artifacts and retains existing proposals', async () => {
  const fake = store(), changes = await pending(fake); await initial(fake, { changes, run: { ...active } });
  await mocked(async (url, options) => {
    if (options.method === 'DELETE') {
      assert.equal(savedChat(fake).messages.at(-1).content, 'Yes, I’m here.');
      assert.deepEqual(savedChat(fake).changes, changes);
      return new Response(null, { status: 204 });
    }
    assert.ok(url.endsWith('/responses/resp_test')); assert.equal(options.method, 'GET');
    return Response.json({ status: 'completed', output: [reply('Yes, I’m here.')] });
  }, async () => {
    const result = await pollWorkspace(fake, config, id);
    assert.equal(result.chat.run.status, 'completed'); assert.equal(result.chat.run.cleanupPending, false);
    assert.deepEqual(result.chat.changes, changes);
  });
});

test('finished file work imports a full multi-file proposal and saves it before remote deletion', async () => {
  const fake = store(); await initial(fake, { run: { ...active } });
  await mocked(async (url, options) => {
    if (options.method === 'DELETE') {
      assert.deepEqual(savedChat(fake).changes.map(change => change.path), ['assets/site.css', 'index.html', 'teaching.html']);
      return new Response(null, { status: 204 });
    }
    if (url.includes('/files?')) return Response.json({ data: [{ id: 'cfile_wrong', path: '/mnt/data/unrelated/review.json' }, { id: 'cfile_review', path: root + '/outputs/review.json', bytes: 500 }], has_more: false });
    if (url.endsWith('/cfile_review/content')) return Response.json({ message: 'Added teaching.', edits: [
      { path: 'teaching.html', content: '<h1>Teaching</h1>', reason: 'New page' },
      { path: 'index.html', content: '<a href="/teaching/">Teaching</a>', reason: 'Navigation' },
      { path: 'assets/site.css', content: 'body { color: blue; }', reason: 'Styling' }
    ] });
    assert.ok(url.endsWith('/responses/resp_test'));
    return Response.json({ status: 'completed', output: [{ type: 'shell_call' }, reply('Added the page and navigation.')] });
  }, async () => {
    const result = await pollWorkspace(fake, config, id);
    assert.equal(result.chat.run.status, 'completed'); assert.equal(result.chat.changes.length, 3);
  });
});

test('a missing export or missing final answer preserves previous changes', async () => {
  for (const output of [[{ type: 'shell_call' }, reply('Done.')], [{ type: 'shell_call' }]]) {
    const fake = store(), changes = await pending(fake); await initial(fake, { changes, run: { ...active } });
    await mocked(async (url, options) => {
      if (options.method === 'DELETE') return new Response(null, { status: 204 });
      return Response.json(url.includes('/files?') ? { data: [], has_more: false } : { status: 'completed', output });
    }, async () => {
      const result = await pollWorkspace(fake, config, id);
      assert.equal(result.chat.run.status, 'failed'); assert.deepEqual(result.chat.changes, changes);
      assert.equal(result.chat.run.failure.responseId, 'resp_test');
    });
  }
});

test('API failure records diagnostics and preserves earlier changes before cleanup', async () => {
  const fake = store(), changes = await pending(fake); await initial(fake, { changes, run: { ...active } });
  await mocked(async (url, options) => {
    if (options.method === 'DELETE') {
      assert.equal(savedChat(fake).run.failure.code, 'internal_error');
      return new Response(null, { status: 204 });
    }
    return Response.json({ status: 'failed', error: { code: 'internal_error', message: 'An internal error occurred.' }, output: [] });
  }, async () => {
    const result = await pollWorkspace(fake, config, id);
    assert.deepEqual(result.chat.changes, changes); assert.equal(result.chat.run.status, 'failed');
    assert.equal(result.chat.run.failure.requestId, 'req_test');
  });
});

test('polling a running response never submits a new paid turn or imports partial changes', async () => {
  const fake = store(); const loaded = await initial(fake, { run: { ...active } });
  await mocked(async (url, options) => {
    assert.equal(options.method, 'GET'); assert.ok(url.endsWith('/responses/resp_test'));
    return Response.json({ status: 'in_progress', output: [reply('I’m checking the homepage.')] });
  }, async () => {
    const result = await pollWorkspace(fake, config, id);
    assert.equal(result.revision, loaded.revision); assert.equal(result.liveMessages[0].content, 'I’m checking the homepage.');
    assert.equal(result.chat.changes.length, 0);
  });
});

test('cancellation targets the stored response and is recoverable on the next poll', async () => {
  const fake = store(); await initial(fake, { run: { ...active } }); let cancellations = 0;
  await mocked(async (url, options) => {
    if (options.method === 'DELETE') return new Response(null, { status: 204 });
    assert.ok(url.endsWith('/responses/resp_test/cancel')); assert.equal(options.method, 'POST'); cancellations++;
    assert.equal(savedChat(fake).run.status, 'cancelling');
    return Response.json({ status: 'cancelled', output: [] });
  }, async () => {
    await cancelWorkspace(fake, config, id);
    const result = await pollWorkspace(fake, config, id);
    assert.equal(result.chat.run.status, 'cancelled'); assert.equal(result.chat.run.cleanupPending, false);
  });
  assert.equal(cancellations, 2);
});

test('cleanup attempts both resources and retries without running the model again', async () => {
  const fake = store(); await initial(fake, { run: { ...active, status: 'completed', cleanupPending: true } }); let failed = true; const deleted = [];
  await mocked(async (url, options) => {
    assert.equal(options.method, 'DELETE'); deleted.push(url);
    return failed && url.includes('/responses/') ? Response.json({ error: { message: 'Unavailable' } }, { status: 500 }) : new Response(null, { status: 204 });
  }, async () => {
    const waiting = await pollWorkspace(fake, config, id);
    assert.equal(waiting.chat.run.cleanupPending, true); assert.ok(deleted.some(url => url.endsWith('/containers/cntr_test')));
    failed = false;
    assert.equal((await pollWorkspace(fake, config, id)).chat.run.cleanupPending, false);
  });
});

test('an uncertain creation does not retry and deletes the known container', async () => {
  const fake = store(); const loaded = await initial(fake); let requests = 0, deleted = false;
  await mocked(async (url, options) => {
    if (options.method === 'DELETE') { deleted = true; return new Response(null, { status: 204 }); }
    if (url.endsWith('/containers')) return Response.json({ id: 'cntr_test' });
    if (url.endsWith('/files')) return Response.json({ path: '/mnt/data/upload-' + options.body.get('file').name });
    requests++; throw new Error('connection lost');
  }, async () => {
    const result = await startWorkspace(fake, config, { id, revision: loaded.revision, prompt: 'Are you working?' });
    assert.equal(result.chat.run.status, 'failed'); assert.match(result.chat.run.error, /No automatic retry/);
  });
  assert.equal(requests, 1); assert.equal(deleted, true);
});

test('upstream failures expose request IDs without leaking API keys', async () => {
  await assert.rejects(responseRequest(config, '/containers', 'POST', {}, async () => Response.json({ error: { code: 'permission_denied', message: 'fake-api-key rejected' } }, { status: 403, headers: { 'x-request-id': 'req_denied' } })), error => error.requestId === 'req_denied' && error.status === 403 && !error.message.includes('fake-api-key'));
});

test('shell networking is optional and accepts only explicitly listed hostnames', () => {
  assert.deepEqual(configuration(env).shellDomains, []);
  assert.deepEqual(configuration({ ...env, OPENAI_SHELL_ALLOWED_DOMAINS: 'rubygems.org, raw.githubusercontent.com' }).shellDomains, ['rubygems.org', 'raw.githubusercontent.com']);
  assert.throws(() => configuration({ ...env, OPENAI_SHELL_ALLOWED_DOMAINS: 'https://rubygems.org/' }), /hostnames/);
});
