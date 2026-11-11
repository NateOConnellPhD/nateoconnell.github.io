import test from 'node:test';
import assert from 'node:assert/strict';
import { sitePath, websiteSnapshot, applySiteProposal, createChat, saveChat, loadChat, deleteChat, prepareChatPublish, validateSiteChanges } from '../lib/site-chat.js';
import { configuration, blobSha, SITE, seal } from '../lib/security.js';
import { handle } from '../api/index.js';

const env = { APP_ORIGIN: 'https://editor.example.com', GITHUB_CLIENT_ID: 'test-client', GITHUB_CLIENT_SECRET: 'test-secret', ALLOWED_GITHUB_USER_ID: '123', SESSION_SECRET: 'ab'.repeat(32), DRAFT_REPOSITORY: 'NateOConnellPhD/editor-private' };
const config = configuration(env);
const id = 'a2345678-1234-4234-9234-123456789abc';
const chat = () => ({ id, title: 'Test chat', messages: [], changes: [] });
const snapshot = content => ({ head: 'public-head', files: new Map(Object.entries(content).map(([path, value]) => [path, { content: value, sha: blobSha(value) }])), occupied: new Set(Object.keys(content)), assets: [] });
const proposal = edits => ({ message: 'Ready for review.', edits });
const edit = (path, content) => ({ path, content, reason: 'Requested change' });

test('site chat supports new pages, code, templates and research including workflows but excludes credentials and private folders', () => {
  for (const path of ['new-page.html', 'teaching.md', 'index.html', '_research/new-paper.md', '_includes/header.html', '_layouts/new-layout.html', 'assets/css/site.css', 'assets/js/site.js', '_config.yml', 'website-editor/api/index.js', '.github/workflows/build.yml', 'CNAME', '_data/publications.json']) assert.equal(sitePath(path, true), true, path);
  for (const path of ['website-editor/.env', '.env', '_posts/../_config.yml', 'assets/css/../../website-editor/lib/security.js', 'Context_not_for_upload/paper.md', 'assets/files/key.pem']) assert.equal(sitePath(path, true), false, path);
  assert.equal(sitePath('_data/publications.json'), true);
});
test('one proposal changes a highlighted selection across papers and homepage without dropping other pending edits', () => {
  const old = snapshot({ '_research/first.md': 'featured: true', '_research/second.md': 'featured: false', 'index.html': 'Four papers', 'assets/css/site.css': 'body{color:blue}' });
  const pending = applySiteProposal([], proposal([edit('assets/css/site.css', 'body{color:navy}')]), old);
  const next = applySiteProposal(pending, proposal([edit('_research/first.md', 'featured: false'), edit('_research/second.md', 'featured: true'), edit('index.html', 'Three papers')]), old);
  assert.equal(next.length, 4); assert.equal(next.find(f => f.path === 'assets/css/site.css').after, 'body{color:navy}');
  assert.equal(next.find(f => f.path === '_research/second.md').beforeSha, blobSha('featured: false'));
  assert.equal(pending.length, 1);
});
test('follow-up edits retain the original baseline and can undo a pending file', () => {
  const old = snapshot({ 'index.html': 'Original' });
  const first = applySiteProposal([], proposal([edit('index.html', 'First edit')]), old);
  const second = applySiteProposal(first, proposal([edit('index.html', 'Second edit')]), old);
  assert.equal(second[0].before, 'Original');
  assert.deepEqual(applySiteProposal(second, proposal([edit('index.html', 'Original')]), old), []);
  const created = applySiteProposal([], proposal([edit('new-page.html', '<h1>New page</h1>')]), old);
  assert.equal(created[0].beforeSha, null);
  assert.deepEqual(applySiteProposal(created, proposal([edit('new-page.html', null)]), old), []);
});
test('unsafe, duplicate, binary and occupied destinations are rejected atomically', () => {
  const old = snapshot({ 'index.html': 'Original' });
  for (const edits of [[edit('index.html', 'Edit'), edit('website-editor/.env', 'anything')], [edit('index.html', 'one'), edit('index.html', 'two')], [edit('index.html', '\0')]]) assert.throws(() => applySiteProposal([], proposal(edits), old));
  old.occupied.add('new-page.html');
  assert.throws(() => applySiteProposal([], proposal([edit('new-page.html', 'overwrite')]), old), /already exists/);
  assert.throws(() => applySiteProposal([], proposal([edit('index.html/child.html', 'nested')]), old), /parent path/);
  assert.throws(() => applySiteProposal([], proposal([edit('new-folder', 'file'), edit('new-folder/child.html', 'nested')]), old), /share the same path/);
  assert.equal(old.files.get('index.html').content, 'Original');
});
test('source snapshot never reads credentials, private context or symlinks and rejects conflicting changes', async () => {
  const reads = [];
  const fake = { head: async () => 'head', tree: async () => ({ entries: [
    { path: 'index.html', type: 'blob', mode: '100644', size: 4, sha: blobSha('test') },
    { path: 'website-editor/.env', type: 'blob', mode: '100644', size: 10 },
    { path: 'Context_not_for_upload/private.md', type: 'blob', mode: '100644', size: 10 },
    { path: 'unsafe.html', type: 'blob', mode: '120000', size: 4 }
  ] }), read: async (repo, path, ref) => { reads.push([repo, path, ref]); return { sha: blobSha('test'), buffer: Buffer.from('test') }; } };
  const result = await websiteSnapshot(fake);
  assert.deepEqual(reads, [[SITE, 'index.html', 'head']]); assert.equal(result.files.size, 1);
  await assert.rejects(websiteSnapshot(fake, [{ path: 'index.html', beforeSha: 'older' }]), /changed/);
});
function privateStore() {
  const files = new Map(), writes = [];
  return { config, files, writes,
    head: async repo => { assert.equal(repo, config.drafts); return 'private-head'; },
    read: async (repo, path) => { assert.equal(repo, config.drafts); const text = files.get(path); return text === undefined ? null : { sha: blobSha(text), buffer: Buffer.from(text) }; },
    readJson: async (repo, path, ref, fallback) => files.has(path) ? JSON.parse(files.get(path)) : structuredClone(fallback),
    commit: async (repo, head, changes) => { assert.equal(repo, config.drafts); writes.push(changes); for (const file of changes) { if (file.content === null) files.delete(file.path); else files.set(file.path, file.content); } return 'private-commit'; }
  };
}
test('conversations persist only in private storage and reject a stale tab', async () => {
  const fake = privateStore(); const created = await createChat(fake);
  created.chat.messages.push({ role: 'user', content: 'Change highlighted papers.' });
  created.chat.changes = applySiteProposal([], proposal([edit('index.html', 'new')]), snapshot({ 'index.html': 'old' }));
  const saved = await saveChat(fake, created.chat, created.revision);
  const loaded = await loadChat(fake, saved.chat.id);
  assert.deepEqual(loaded, saved);
  await assert.rejects(saveChat(fake, created.chat, created.revision), /another tab/);
  assert.equal(fake.writes.length, 2);
});
test('publication detects simultaneous public changes and preserves a multi-file transaction', async () => {
  const pending = chat(); const old = snapshot({ 'index.html': 'old', 'assets/css/site.css': 'old css' });
  pending.changes = applySiteProposal([], proposal([edit('index.html', 'new'), edit('assets/css/site.css', 'new css')]), old);
  const entries = [...old.files].map(([path, file]) => ({ path, sha: file.sha, type: 'blob', mode: '100644' }));
  const fake = { head: async () => 'latest', tree: async () => ({ entries }) };
  const plan = await prepareChatPublish(fake, pending);
  assert.equal(plan.files.length, 2); assert.equal(plan.head, 'latest');
  entries[0].sha = 'concurrent-edit';
  await assert.rejects(prepareChatPublish(fake, pending), /changed/);
});
test('JSON validation rejects invalid output before saving or publishing', async () => {
  await assert.rejects(validateSiteChanges([{ path: '_data/new-data.json', before: null, after: 'not json', reason: 'Add data' }]), /Invalid JSON/);
});
test('site-chat publication needs its own review receipt and rejects CSRF before reading private storage', async () => {
  const savedEnv = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]])); const transport = globalThis.fetch; const calls = [];
  try {
    Object.assign(process.env, env);
    globalThis.fetch = async (url, options) => { calls.push(options.method); assert.equal(url, `https://api.github.com/repos/${config.drafts}`); return Response.json({ private: true, fork: false, owner: { login: 'NateOConnellPhD' }, default_branch: 'main' }); };
    const token = seal({ id: 123, token: 'test-token', csrf: 'csrf' }, 'session', config);
    const request = (csrf, receipt) => new Request(`${config.origin}/api/chat/publish`, { method: 'POST', headers: { Cookie: `__Host-site-editor=${token}`, Origin: config.origin, 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }, body: JSON.stringify({ id, receipt }) });
    assert.equal((await handle(request('wrong', 'forged'))).status, 403); assert.equal(calls.length, 0);
    const pageReceipt = seal({ id }, 'publish-review', config);
    assert.equal((await handle(request('csrf', pageReceipt))).status, 409); assert.deepEqual(calls, ['GET']);
  } finally { globalThis.fetch = transport; for (const [key, value] of Object.entries(savedEnv)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; } }
});

test('deleting a chat atomically removes its conversation and preview while preserving other chats and drafts', async () => {
  const fake = privateStore(), first = await createChat(fake), other = await createChat(fake);
  const previewPath = `chats/previews/${first.chat.id}.json`;
  fake.files.set(previewPath, '{"pages":[]}');
  fake.files.set(`chats/previews/${other.chat.id}.json`, '{"pages":[]}');
  fake.files.set('drafts/other.json', 'independent document draft');
  first.chat.changes = applySiteProposal([], proposal([edit('index.html', 'private edit')]), snapshot({ 'index.html': 'published' }));
  const saved = await saveChat(fake, first.chat, first.revision);
  const before = fake.writes.length;
  assert.deepEqual(await deleteChat(fake, first.chat.id, saved.revision), { deleted: first.chat.id });
  assert.equal(fake.writes.length, before + 1);
  assert.deepEqual(fake.writes.at(-1).map(file => file.path).sort(), [`chats/${first.chat.id}.json`, 'chats/index.json', previewPath].sort());
  assert.equal(fake.files.has(`chats/${first.chat.id}.json`), false); assert.equal(fake.files.has(previewPath), false);
  assert.deepEqual(JSON.parse(fake.files.get('chats/index.json')).chats.map(entry => entry.id), [other.chat.id]);
  assert.ok(fake.files.has(`chats/${other.chat.id}.json`)); assert.ok(fake.files.has(`chats/previews/${other.chat.id}.json`));
  assert.equal(fake.files.get('drafts/other.json'), 'independent document draft');
  await assert.rejects(saveChat(fake, saved.chat, saved.revision), /another tab/);
});

test('empty and failed test chats can be deleted without requiring a preview', async () => {
  for (const status of [null, 'failed', 'cancelled', 'completed']) {
    const fake = privateStore(), created = await createChat(fake);
    if (status) { created.chat.run = { status }; Object.assign(created, await saveChat(fake, created.chat, created.revision)); }
    await deleteChat(fake, created.chat.id, created.revision);
    assert.deepEqual(JSON.parse(fake.files.get('chats/index.json')).chats, []);
    assert.equal(fake.writes.at(-1).length, 2);
  }
});

test('stale or repeated deletion cannot remove newer changes', async () => {
  const fake = privateStore(), created = await createChat(fake);
  created.chat.messages.push({ role: 'user', content: 'Keep this new message' });
  const changed = await saveChat(fake, created.chat, created.revision), before = fake.writes.length;
  await assert.rejects(deleteChat(fake, created.chat.id, created.revision), error => error.status === 409);
  assert.equal(fake.writes.length, before); assert.equal((await loadChat(fake, created.chat.id)).chat.messages.at(-1).content, 'Keep this new message');
  await deleteChat(fake, created.chat.id, changed.revision);
  await assert.rejects(deleteChat(fake, created.chat.id, changed.revision), error => error.status === 404);
  assert.equal(fake.writes.length, before + 1);
});

test('deletion cannot orphan a running response or pending remote cleanup', async () => {
  for (const run of [{ status: 'starting' }, { status: 'in_progress' }, { status: 'cancelling' }, { status: 'failed', cleanupPending: true }, { status: 'failed', lookupPending: true }]) {
    const fake = privateStore(), created = await createChat(fake);
    created.chat.run = run;
    const saved = await saveChat(fake, created.chat, created.revision), before = fake.writes.length;
    await assert.rejects(deleteChat(fake, created.chat.id, saved.revision), error => error.status === 409);
    assert.equal(fake.writes.length, before); assert.ok(fake.files.has(`chats/${created.chat.id}.json`));
  }
});

test('deletion uses a validated chat ID and leaves storage intact when its commit conflicts', async () => {
  const fake = privateStore(), created = await createChat(fake);
  await assert.rejects(deleteChat(fake, '../other', created.revision), /Invalid draft ID/);
  const before = new Map(fake.files);
  fake.commit = async () => { throw new Error('Concurrent commit'); };
  await assert.rejects(deleteChat(fake, created.chat.id, created.revision), /Concurrent commit/);
  assert.deepEqual(fake.files, before);
});

test('chat deletion requires sign-in and CSRF before accessing private storage', async () => {
  const savedEnv = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]])); const transport = globalThis.fetch; let calls = 0;
  try {
    Object.assign(process.env, env);
    globalThis.fetch = async () => { calls++; throw new Error('Unauthorized deletion reached storage'); };
    const token = seal({ id: 123, token: 'test-token', csrf: 'csrf' }, 'session', config);
    const request = (cookie, csrf) => new Request(`${config.origin}/api/chat/delete`, { method: 'POST', headers: { Cookie: cookie, Origin: config.origin, 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }, body: JSON.stringify({ id, revision: 'test' }) });
    assert.equal((await handle(request('', 'csrf'))).status, 401);
    assert.equal((await handle(request(`__Host-site-editor=${token}`, 'wrong'))).status, 403);
    assert.equal(calls, 0);
  } finally { globalThis.fetch = transport; for (const [key, value] of Object.entries(savedEnv)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; } }
});
