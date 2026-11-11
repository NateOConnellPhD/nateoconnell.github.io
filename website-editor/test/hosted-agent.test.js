import test from 'node:test';
import assert from 'node:assert/strict';
import { agentRequest, startWorkspace, pollWorkspace, cancelWorkspace } from '../lib/hosted-agent.js';
import { blobSha, configuration, SITE } from '../lib/security.js';
import { saveChat, applySiteProposal } from '../lib/site-chat.js';

const config = { ...configuration({ APP_ORIGIN: 'https://editor.example', GITHUB_CLIENT_ID: 'client', GITHUB_CLIENT_SECRET: 'secret', ALLOWED_GITHUB_USER_ID: '1', SESSION_SECRET: 'ab'.repeat(32), DRAFT_REPOSITORY: 'NateOConnellPhD/editor-private' }), apiKey: 'fake-api-key' };
const id = 'a2345678-1234-4234-9234-123456789abc';
function store() {
  const files = new Map(), publicFiles = new Map([['index.html', '<h1>Nate</h1>']]); const writes = [];
  return { config, files, publicFiles, writes,
    head: async repo => repo === SITE ? 'public-head' : 'private-head',
    tree: async () => ({ entries: [...publicFiles].map(([path, content]) => ({ path, sha: blobSha(content), type: 'blob', mode: '100644', size: content.length })) }),
    read: async (repo, path) => { const content = (repo === SITE ? publicFiles : files).get(path); return content === undefined ? null : { sha: blobSha(content), buffer: Buffer.from(content) }; },
    readJson: async (repo, path, ref, fallback) => files.has(path) ? JSON.parse(files.get(path)) : structuredClone(fallback),
    commit: async (repo, head, changes) => { assert.equal(repo, config.drafts, 'Model operations must never write the public repository'); writes.push(changes); for (const change of changes) files.set(change.path, change.content); return 'private-commit'; }
  };
}
async function initial(fake, extra = {}) { return saveChat(fake, { id, title: 'New chat', messages: [], changes: [], ...extra }, null); }

test('a hosted task accepts an empty HTTP 202 after saving its session and keeps credentials outside the sandbox', async () => {
  const fake = store(), loaded = await initial(fake), originalFetch = globalThis.fetch; const calls = [];
  try {
    globalThis.fetch = async (url, options) => {
      const body = options.body && JSON.parse(options.body); calls.push({ url, options, body });
      if (url.endsWith('/sessions')) {
        assert.equal(body.input, undefined); assert.equal(body.environment.type, 'openai_hosted');
        assert.ok(body.environment.files.some(file => file.path === '/workspace/workspace.py'));
        assert.ok(!JSON.stringify(body).includes('fake-api-key')); assert.equal(body.agent.multi_agent.enabled, false);
        return Response.json({ id: 'sess_test', status: 'idle' });
      }
      assert.ok(JSON.parse(fake.files.get(`chats/${id}.json`)).run.sessionId === 'sess_test');
      return new Response(null, { status: 202 });
    };
    const result = await startWorkspace(fake, config, { id, revision: loaded.revision, prompt: 'Add a teaching page and build it.' });
    assert.equal(result.chat.run.status, 'submitting'); assert.equal(calls.length, 2);
    assert.equal(calls[1].options.headers['Idempotency-Key'], result.chat.run.key);
    assert.equal(result.chat.changes.length, 0);
    const stored = JSON.parse(fake.files.get(`chats/${id}.json`));
    assert.equal(stored.messages[0].content, 'Add a teaching page and build it.');
    assert.equal(stored.run.sessionId, 'sess_test');
    assert.equal(stored.run.error, undefined);
  } finally { globalThis.fetch = originalFetch; }
});
test('polling a running task does not call it complete or apply partial results', async () => {
  const fake = store(); const loaded = await initial(fake, { run: { sessionId: 'sess_test', key: 'same-key', status: 'submitting', prompt: 'Edit', head: 'public-head' } });
  const originalFetch = globalThis.fetch; const calls = [];
  try {
    globalThis.fetch = async (url, options) => { calls.push({ url, options }); if (url.includes('/events')) return new Response(null, { status: 202 }); if (url.includes('/turns')) return Response.json({ data: [{ id: 'turn_test', subagent_id: null, status: 'in_progress' }] }); return Response.json({ status: 'in_progress' }); };
    const result = await pollWorkspace(fake, config, id);
    assert.equal(result.revision, loaded.revision); assert.equal(result.chat.changes.length, 0);
    assert.equal(calls[0].options.headers['Idempotency-Key'], 'same-key');
  } finally { globalThis.fetch = originalFetch; }
});
test('only an artifact from the completed main turn is imported, then the sandbox is deleted', async () => {
  const fake = store(); await initial(fake, { messages: [{ role: 'user', content: 'Add teaching' }], run: { sessionId: 'sess_test', key: 'key', status: 'submitting', prompt: 'Add teaching', head: 'public-head' } });
  const originalFetch = globalThis.fetch; let deleted = false;
  try {
    globalThis.fetch = async (url, options) => {
      if (options.method === 'DELETE') { deleted = true; return new Response(null, { status: 204 }); }
      if (url.includes('/events')) return new Response(null, { status: 202 });
      if (url.includes('/turns')) return Response.json({ data: [{ id: 'turn_new', subagent_id: null, status: 'completed' }] });
      if (url.includes('/artifacts?')) return Response.json({ data: [
        { id: 'artifact_old', turn_id: 'turn_old', path: '/workspace/outputs/review.json', size_bytes: 100 },
        { id: 'artifact_new', turn_id: 'turn_new', path: '/workspace/outputs/review.json', size_bytes: 200 }
      ] });
      if (url.endsWith('/artifact_new/content')) return Response.json({ message: 'Added teaching. Build succeeded in the cloud.', edits: [{ path: 'teaching.html', content: '<h1>Teaching</h1>', reason: 'New page' }] });
      assert.ok(!url.includes('artifact_old')); return Response.json({ status: 'idle' });
    };
    const result = await pollWorkspace(fake, config, id);
    assert.equal(result.chat.run.status, 'completed'); assert.equal(result.chat.changes[0].path, 'teaching.html'); assert.equal(result.chat.messages.length, 2); assert.equal(deleted, true);
  } finally { globalThis.fetch = originalFetch; }
});
test('failed remote work preserves previous pending changes and cancellation targets the saved session', async () => {
  const fake = store(); const pending = [{ path: 'index.html', before: '<h1>Nate</h1>', beforeSha: blobSha('<h1>Nate</h1>'), after: '<h1>Nate, PhD</h1>', reason: 'Credential' }];
  await initial(fake, { changes: pending, run: { sessionId: 'sess_test', key: 'key', status: 'submitting', prompt: 'Build', head: 'public-head' } });
  const originalFetch = globalThis.fetch; const requests = [];
  try {
    globalThis.fetch = async (url, options) => { requests.push({ url, body: options.body && JSON.parse(options.body) }); if (options.method === 'DELETE') return new Response(null, { status: 204 }); if (url.includes('/events')) return new Response(null, { status: 202 }); if (url.includes('/turns')) return Response.json({ data: [{ subagent_id: null, status: 'failed', error: { message: 'Build tools unavailable' } }] }); return Response.json({ status: 'idle' }); };
    await cancelWorkspace(fake, config, id);
    assert.ok(requests.some(item => item.body?.events[0].type === 'agent.session.input.cancel'));
    assert.equal(requests.filter(item => item.body?.events[0].type === 'agent.session.input.message').length, 1);
    const result = await pollWorkspace(fake, config, id);
    assert.deepEqual(result.chat.changes, pending); assert.equal(result.chat.run.status, 'failed');
  } finally { globalThis.fetch = originalFetch; }
});
test('cloud access errors are actionable without leaking upstream credentials', async () => {
  for (const path of ['/sessions', '/sessions/sess_test/events']) {
    await assert.rejects(agentRequest(config, path, 'POST', {}, null, async () => Response.json({ error: 'fake-api-key' }, { status: 403 })), error => /Agents read\/write/.test(error.message) && !error.message.includes('fake-api-key'));
  }
});
test('an interrupted start recovers its recorded request instead of creating another session', async () => {
  const fake = store(); await initial(fake, { run: { key: 'recover-key', status: 'starting', started: Date.now() - 180000, prompt: 'Edit', head: 'public-head' } });
  const originalFetch = globalThis.fetch; const calls = [];
  try {
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options });
      if (url.includes('/sessions?')) return Response.json({ data: [{ id: 'sess_recovered', metadata: { editor_chat: id, request: 'recover-key' } }] });
      assert.ok(url.endsWith('/sessions/sess_recovered/events')); return new Response(null, { status: 202 });
    };
    const result = await pollWorkspace(fake, config, id);
    assert.equal(result.chat.run.sessionId, 'sess_recovered');
    assert.equal(calls[1].options.headers['Idempotency-Key'], 'recover-key');
    assert.equal(calls.some(call => call.url.endsWith('/sessions')), false);
  } finally { globalThis.fetch = originalFetch; }
});
test('cleanup failures remain recoverable without importing or publishing the result twice', async () => {
  const fake = store(); await initial(fake, { run: { sessionId: 'sess_test', key: 'key', status: 'completed', cleanupPending: true } });
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url, options) => { assert.equal(options.method, 'DELETE'); return Response.json({}, { status: 409 }); };
    const waiting = await pollWorkspace(fake, config, id);
    assert.equal(waiting.chat.run.cleanupPending, true); assert.match(waiting.cleanupWarning, /pending/);
    globalThis.fetch = async (url, options) => { assert.equal(options.method, 'DELETE'); return new Response(null, { status: 204 }); };
    const cleaned = await pollWorkspace(fake, config, id);
    assert.equal(cleaned.chat.run.cleanupPending, false); assert.equal(cleaned.chat.changes.length, 0);
  } finally { globalThis.fetch = originalFetch; }
});
test('a completed turn with no export preserves earlier working changes and requests cleanup', async () => {
  const fake = store(); const pending = [{ path: 'index.html', before: '<h1>Nate</h1>', beforeSha: blobSha('<h1>Nate</h1>'), after: '<h1>Nate, PhD</h1>', reason: 'Credential' }];
  await initial(fake, { changes: pending, run: { sessionId: 'sess_test', key: 'key', status: 'submitting', prompt: 'Edit', head: 'public-head' } });
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url, options) => {
      if (options.method === 'DELETE') return new Response(null, { status: 204 });
      if (url.includes('/events')) return new Response(null, { status: 202 });
      if (url.includes('/turns')) return Response.json({ data: [{ id: 'turn_new', subagent_id: null, status: 'completed' }] });
      if (url.includes('/artifacts?')) return Response.json({ data: [] });
      return Response.json({ status: 'idle' });
    };
    const result = await pollWorkspace(fake, config, id);
    assert.equal(result.chat.run.status, 'failed'); assert.equal(result.chat.run.cleanupPending, false);
    assert.deepEqual(result.chat.changes, pending);
  } finally { globalThis.fetch = originalFetch; }
});
test('binary updates preserve the original blob identity and keep private bytes out of text previews', () => {
  const original = Buffer.from([137, 80, 78, 71, 0]);
  const snapshot = { files: new Map(), occupied: new Set(['assets/images/test.png']), binaries: new Map([['assets/images/test.png', { sha: blobSha(original), binary: true, mode: '100644' }]]) };
  const changes = applySiteProposal([], { message: 'Replace image', edits: [{ path: 'assets/images/test.png', content: Buffer.from([137, 80, 78, 71, 1]).toString('base64'), encoding: 'base64', reason: 'New image' }] }, snapshot);
  assert.equal(changes[0].beforeSha, blobSha(original)); assert.equal(changes[0].binaryBefore, true); assert.equal(changes[0].before, null);
});
