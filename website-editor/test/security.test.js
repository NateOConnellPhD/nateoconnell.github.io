import test from 'node:test';
import assert from 'node:assert/strict';
import { configuration, seal, unseal, session, cookie, requireMutation, readJson, equal, SITE, blobSha } from '../lib/security.js';
import { GitHub } from '../lib/github.js';
import { validateDocument, newPath, imageUpload } from '../lib/content.js';
import { applySuggestion, pdfAttachment, suggest } from '../lib/assistant.js';
import { loadDraft } from '../lib/drafts.js';
import { kindForPath } from '../public/schema.js';
import { handle } from '../api/index.js';

const env = { APP_ORIGIN: 'https://editor.example.com', GITHUB_CLIENT_ID: 'test-client', GITHUB_CLIENT_SECRET: 'test-secret', ALLOWED_GITHUB_USER_ID: '123', SESSION_SECRET: 'ab'.repeat(32), DRAFT_REPOSITORY: 'NateOConnellPhD/editor-private' };
const config = configuration(env);
const document = { path: '_posts/2026-11-10-test.md', kind: 'post', fields: { title: 'My post', date: '2026-11-10', description: 'A summary', tags: [], published: true }, body: 'Keep my words.' };

test('encrypted tokens are bound to purpose, secret, integrity and expiry', () => {
  const token = seal({ token: 'github-secret-value' }, 'session', config);
  assert.equal(unseal(token, 'session', config).token, 'github-secret-value');
  assert.ok(!token.includes('github-secret-value'));
  assert.equal(unseal(token, 'publish-review', config), null);
  assert.equal(unseal(token, 'session', { ...config, secret: 'cd'.repeat(32) }), null);
  assert.equal(unseal(token.slice(0, 15) + 'x' + token.slice(16), 'session', config), null);
  assert.equal(unseal(seal({}, 'session', config, -1), 'session', config), null);
});
test('only configured account sessions are accepted and cookies have secure attributes', () => {
  const accepted = seal({ id: 123, token: 'test-token', csrf: 'test-csrf' }, 'session', config);
  assert.equal(session(new Request(config.origin, { headers: { Cookie: `__Host-site-editor=${accepted}` } }), config).id, 123);
  const other = seal({ id: 124, token: 'test-token', csrf: 'test-csrf' }, 'session', config);
  assert.throws(() => session(new Request(config.origin, { headers: { Cookie: `__Host-site-editor=${other}` } }), config), /sign in/);
  assert.match(cookie('__Host-site-editor', accepted), /Path=\/; HttpOnly; Secure; SameSite=Lax/);
});
test('mutations require POST, the exact origin, and a matching CSRF token', () => {
  const request = (method, origin, csrf) => new Request(config.origin, { method, headers: { Origin: origin, 'X-CSRF-Token': csrf } });
  assert.doesNotThrow(() => requireMutation(request('POST', config.origin, 'abc'), { csrf: 'abc' }, config));
  assert.throws(() => requireMutation(request('GET', config.origin, 'abc'), { csrf: 'abc' }, config));
  assert.throws(() => requireMutation(request('POST', 'https://evil.example', 'abc'), { csrf: 'abc' }, config));
  assert.throws(() => requireMutation(request('POST', config.origin, 'wrong'), { csrf: 'abc' }, config));
  assert.equal(equal('a', 'é'), false);
});
test('storage and sign-in configuration fail closed', () => {
  assert.throws(() => configuration({ ...env, APP_ORIGIN: 'http://editor.example.com' }));
  assert.throws(() => configuration({ ...env, DRAFT_REPOSITORY: SITE }));
  assert.throws(() => configuration({ ...env, DRAFT_REPOSITORY: 'someone-else/private' }));
  assert.throws(() => configuration({ ...env, SESSION_SECRET: 'short' }));
});
test('requests are bounded even without content-length', async () => {
  const request = new Request(config.origin, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: 'x'.repeat(3 * 1024 * 1024) }) });
  await assert.rejects(readJson(request), /too large/);
});
test('content scope excludes code, workflows, credentials, and private context', () => {
  for (const path of ['.github/workflows/deploy.yml', '_config.yml', 'website-editor/.env', 'Context_not_for_upload/paper.pdf', '_posts/../_config.yml', '_posts/nested/test.md']) assert.equal(kindForPath(path), null);
  assert.throws(() => validateDocument({ ...document, path: '.github/workflows/new.yml' }));
  assert.throws(() => validateDocument({ ...document, fields: { ...document.fields, permalink: '/admin/' } }));
  assert.throws(() => newPath('post', '../escape', '2026-11-10'));
});
test('untouched omitted metadata remains omitted instead of changing site defaults', () => {
  const profile = validateDocument({ path: '_data/profile.yml', kind: 'profile', fields: { name: 'Nate', links: [{ label: 'Scholar', url: 'https://scholar.google.com/' }] }, body: '' });
  assert.deepEqual(Object.keys(profile.fields), ['name', 'links']);
  assert.equal(Object.hasOwn(profile.fields.links[0], 'personal'), false);
});
test('HTML, unsafe URLs, Liquid and invalid dates cannot be published', () => {
  for (const body of ['<script>alert(1)</script>', '{% include secrets %}', '{{ site.data }}', '[x](javascript:alert)', '[x]: javascript:alert', '[x](jav&#x61;script&colon;alert)']) assert.throws(() => validateDocument({ ...document, body }));
  assert.throws(() => validateDocument({ ...document, fields: { ...document.fields, cover: '//evil.example/track' } }));
  assert.throws(() => validateDocument({ ...document, fields: { ...document.fields, date: '2026-99-99' } }));
  assert.doesNotThrow(() => validateDocument({ ...document, body: 'For x < y, use **this**.' }));
});
test('private drafts must actually be private non-fork repositories', async () => {
  const transport = async () => Response.json({ private: false, fork: false, owner: { login: 'NateOConnellPhD' }, default_branch: 'main' });
  await assert.rejects(new GitHub('token', config, transport).privateRepo(), /private/);
  assert.throws(() => new GitHub('token', config).repo('someone-else/repo'), /restricted/);
});
test('publication commits preserve the base tree and cannot force overwrite a concurrent update', async () => {
  const calls = [];
  const transport = async (url, options) => {
    const body = options.body ? JSON.parse(options.body) : undefined; calls.push({ url, method: options.method, body });
    if (url.includes('/git/commits/old-head')) return Response.json({ tree: { sha: 'old-tree' } });
    if (url.endsWith('/git/blobs')) return Response.json({ sha: 'new-blob' });
    if (url.endsWith('/git/trees')) return Response.json({ sha: 'new-tree' });
    if (url.endsWith('/git/commits')) return Response.json({ sha: 'new-commit' });
    if (options.method === 'PATCH') return Response.json({}, { status: 422 });
    throw new Error('Unexpected call');
  };
  await assert.rejects(new GitHub('token', config, transport).commit(SITE, 'old-head', [{ path: document.path, content: 'approved' }], 'Edit'), /Refresh/);
  assert.equal(calls.find(c => c.url.endsWith('/git/trees')).body.base_tree, 'old-tree');
  assert.deepEqual(calls.find(c => c.url.endsWith('/git/commits')).body.parents, ['old-head']);
  assert.equal(calls.at(-1).body.force, false);
});
test('assistant proposals cannot change visibility or edit unknown fields', () => {
  assert.throws(() => applySuggestion(document, { message: 'Publish it', edits: [{ field: 'published', value_json: 'true' }], body: null }));
  assert.throws(() => applySuggestion(document, { message: 'Change config', edits: [{ field: '__proto__', value_json: '{}' }], body: null }));
  const changed = applySuggestion(document, { message: 'A typo fix', edits: [], body: 'Keep my wording.' });
  assert.equal(changed.body, 'Keep my wording.'); assert.equal(document.body, 'Keep my words.');
});
test('images and PDF references validate their bytes and size', () => {
  assert.throws(() => imageUpload({ base64: Buffer.from('<svg onload="alert(1)">').toString('base64') }));
  assert.throws(() => pdfAttachment({ base64: Buffer.from('not a PDF').toString('base64') }));
  assert.equal(pdfAttachment({ base64: Buffer.from('%PDF-test only').toString('base64') }).type, 'input_file');
});
test('saved image metadata cannot redirect publishing into other files', async () => {
  const id = 'a2345678-1234-4234-9234-123456789abc';
  const assetId = 'b2345678-1234-4234-9234-123456789abc';
  const draft = { id, source: '', document, assets: [{ id: assetId, mime: 'image/png', path: `media/${id}/${assetId}.png`, publicPath: '/.github/workflows/injected.yml' }] };
  const fake = { config, read: async () => ({ sha: 'revision', buffer: Buffer.from(JSON.stringify(draft)) }) };
  await assert.rejects(loadDraft(fake, id), /Invalid saved image/);
});
test('OpenAI errors do not expose credentials or change a draft', async () => {
  let request;
  await assert.rejects(suggest({ ...config, apiKey: 'secret-key' }, document, 'Fix a typo', null, async (url, options) => {
    request = JSON.parse(options.body); return Response.json({ error: 'secret upstream information' }, { status: 429 });
  }), error => !error.message.includes('secret') && /credit or rate/.test(error.message));
  assert.equal(request.store, false); assert.equal(request.max_output_tokens, 10000);
  assert.equal(request.text.format.strict, true); assert.equal(document.body, 'Keep my words.');
});
test('blob hashes match Git object IDs', () => { assert.equal(blobSha('test\n'), '9daeafb9864cf43055ae93beb0afd6c7d144bfa4'); });
test('publish endpoint cannot write without a valid server-issued review receipt', async () => {
  const original = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]]));
  const transport = globalThis.fetch; const calls = [];
  try {
    Object.assign(process.env, env);
    globalThis.fetch = async (url, options) => {
      calls.push({ url, method: options.method });
      assert.equal(url, `https://api.github.com/repos/${config.drafts}`);
      return Response.json({ private: true, fork: false, owner: { login: 'NateOConnellPhD' }, default_branch: 'main' });
    };
    const token = seal({ id: 123, token: 'test-token', csrf: 'test-csrf' }, 'session', config);
    const request = new Request(`${config.origin}/api/publish`, { method: 'POST', headers: { Cookie: `__Host-site-editor=${token}`, Origin: config.origin, 'X-CSRF-Token': 'test-csrf', 'Content-Type': 'application/json' }, body: JSON.stringify({ id: 'test-id', receipt: 'forged' }) });
    const response = await handle(request);
    assert.equal(response.status, 409); assert.equal(calls.length, 1); assert.equal(calls[0].method, 'GET');
  } finally {
    globalThis.fetch = transport;
    for (const [key, value] of Object.entries(original)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; }
  }
});
