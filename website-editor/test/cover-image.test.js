import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { addImage, draftPath, loadDraft, preparePublish, updateDraft } from '../lib/drafts.js';
import { blobSha, SITE } from '../lib/security.js';

const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=';
function repository() {
  const id = randomUUID(), files = new Map(); let version = 0;
  const document = { path: '_posts/2000-01-01-example.md', kind: 'post', fields: { title: 'Example', date: '2000-01-01', description: 'My own description.', cover: '/assets/images/original.png', cover_alt: 'My illustration', cover_caption: 'My caption', published: true }, body: 'Keep my writing and $$x_i^2$$ exactly as they are.' };
  files.set(draftPath(id), JSON.stringify({ id, document, source: '', sourceSha: null, assets: [] }));
  return {
    id, files, writes: [], config: { drafts: 'private' },
    async head() { return String(version); },
    async read(repo, path) {
      if (repo === SITE) { assert.equal(path, document.path); return null; }
      assert.equal(repo, 'private'); const content = files.get(path);
      return content === undefined ? null : { sha: blobSha(content), buffer: Buffer.from(content) };
    },
    async readJson(repo, path, ref, fallback) { const file = await this.read(repo, path); return file ? JSON.parse(file.buffer.toString()) : fallback; },
    async commit(repo, head, changes) {
      assert.equal(repo, 'private'); assert.equal(head, String(version)); version++;
      this.writes.push(changes.map(file => file.path));
      for (const file of changes) files.set(file.path, file.content);
    }
  };
}

test('cover upload and replacement persist atomically and removal preserves writing and stored images', async () => {
  const github = repository(), initial = await loadDraft(github, github.id);
  const uploaded = await addImage(github, { id: github.id, revision: initial.revision, field: 'cover', base64: png });
  assert.equal(github.writes.length, 1);
  assert.deepEqual(github.writes[0], [draftPath(github.id), 'index.json', uploaded.asset.path]);
  const saved = await loadDraft(github, github.id);
  assert.deepEqual(saved.draft.document, { ...initial.draft.document, fields: { ...initial.draft.document.fields, cover: uploaded.asset.publicPath } });
  const replaced = await addImage(github, { id: github.id, revision: saved.revision, field: 'cover', base64: png });
  assert.notEqual(replaced.asset.publicPath, uploaded.asset.publicPath);
  assert.equal((await loadDraft(github, github.id)).draft.document.fields.cover, replaced.asset.publicPath);
  assert.equal(replaced.draft.document.body, initial.draft.document.body);
  const removed = await updateDraft(github, { id: github.id, revision: replaced.revision, document: { ...replaced.draft.document, fields: { ...replaced.draft.document.fields, cover: '' } } });
  assert.deepEqual((await loadDraft(github, github.id)).draft.document, { ...initial.draft.document, fields: { ...initial.draft.document.fields, cover: '' } });
  assert.equal(removed.draft.assets.length, 2);
  assert.ok(github.files.has(uploaded.asset.path)); // Removing a cover does not delete an image used elsewhere.
});

test('publication includes the selected cover without inserting it in the post body', async () => {
  const github = repository(), initial = await loadDraft(github, github.id);
  const first = await addImage(github, { id: github.id, revision: initial.revision, field: 'cover', base64: png });
  const replacement = await addImage(github, { id: github.id, revision: first.revision, field: 'cover', base64: png });
  const plan = await preparePublish(github, replacement.draft);
  assert.deepEqual(plan.files.map(file => file.path), [initial.draft.document.path, replacement.asset.publicPath.slice(1)]);
  assert.equal(plan.files[1].content.toString('base64'), png);
  assert.ok(plan.content.includes(`cover: ${replacement.asset.publicPath}`));
  assert.equal(replacement.draft.document.body, initial.draft.document.body);
  const removed = await updateDraft(github, { id: github.id, revision: replacement.revision, document: { ...replacement.draft.document, fields: { ...replacement.draft.document.fields, cover: '' } } });
  assert.deepEqual((await preparePublish(github, removed.draft)).files.map(file => file.path), [initial.draft.document.path]);
});

test('invalid or stale cover uploads leave the saved cover unchanged', async () => {
  const github = repository(), original = await loadDraft(github, github.id);
  const request = { id: github.id, revision: original.revision, field: 'cover', base64: png };
  await assert.rejects(addImage(github, { ...request, field: 'title' }), /supported image field/);
  await assert.rejects(addImage(github, { ...request, base64: Buffer.from('This is not an image.').toString('base64') }), /Choose a PNG/);
  await assert.rejects(addImage(github, { ...request, revision: 'stale' }), /Save or reload/);
  assert.deepEqual(await loadDraft(github, github.id), original);
  assert.equal(github.writes.length, 0);
});

test('body image uploads leave the cover and writing unchanged', async () => {
  const github = repository(), original = await loadDraft(github, github.id);
  const result = await addImage(github, { id: github.id, revision: original.revision, base64: png });
  assert.deepEqual(result.draft.document, original.draft.document);
  assert.equal(result.draft.assets.length, 1);
});
