import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { parseSource, serialize, validateDocument } from '../lib/content.js';
import { preparePublish } from '../lib/drafts.js';
import { schemas } from '../public/schema.js';

const root = new URL('../../', import.meta.url);
test('blog descriptions may be drafted empty but must be present before publishing', () => {
  const document = { path: '_posts/2000-01-01-example.md', kind: 'post', fields: { title: 'Example', date: '2000-01-01', published: true }, body: 'Post body.' };
  for (const description of [undefined, '', '   ']) {
    const draft = structuredClone(document);
    if (description !== undefined) draft.fields.description = description;
    assert.doesNotThrow(() => validateDocument(draft));
    assert.throws(() => validateDocument(draft, true), /Short description is required before publishing/);
  }
  const described = { ...document, fields: { ...document.fields, description: 'The author’s short description.' } };
  assert.equal(validateDocument(described, true).fields.description, described.fields.description);
});
test('all existing editable documents can be opened and round-tripped without losing fields', async () => {
  const files = Object.values(schemas).filter(s => s.path).map(s => s.path);
  for (const folder of ['_posts', '_research', '_talks']) for (const file of await readdir(new URL(folder + '/', root))) if (file.endsWith('.md')) files.push(`${folder}/${file}`);
  for (const path of files) {
    const source = await readFile(new URL(path, root), 'utf8');
    const parsed = await parseSource(path, source);
    const rebuilt = await serialize(parsed, source);
    assert.deepEqual(await parseSource(path, rebuilt), parsed, path);
    if (source.includes('published: false')) assert.ok(rebuilt.includes('published: false'), path);
    for (const key of ['layout:', 'permalink:', 'example:']) if (source.includes(key)) assert.ok(rebuilt.includes(key), `${path}: ${key}`);
  }
});
test('a stale website version stops publication before any writes', async () => {
  const document = { path: '_posts/2026-11-10-example.md', kind: 'post', fields: { title: 'Example', date: '2026-11-10', description: 'Test', published: true }, body: 'Only a test.' };
  const github = { config: { drafts: 'private' }, head: async () => 'new-head', read: async () => ({ sha: 'new-source' }) };
  await assert.rejects(preparePublish(github, { document, source: '', sourceSha: 'old-source', assets: [] }), /website changed/);
});
test('review reads only referenced draft images and does not write public objects', async () => {
  const document = { path: '_posts/2026-11-10-example.md', kind: 'post', fields: { title: 'Example', date: '2026-11-10', description: 'Test', published: true }, body: '![Test](/assets/images/one.png)' };
  const read = [];
  const github = { config: { drafts: 'private' }, head: async () => 'head', read: async (repo, path) => {
    read.push(path); return path === document.path ? null : { buffer: Buffer.from('image bytes') };
  } };
  const plan = await preparePublish(github, { document, source: '', sourceSha: null, assets: [{ path: 'private/one.png', publicPath: '/assets/images/one.png' }, { path: 'private/two.png', publicPath: '/assets/images/two.png' }] });
  assert.deepEqual(read, [document.path, 'private/one.png']); assert.equal(plan.files.length, 2);
});
