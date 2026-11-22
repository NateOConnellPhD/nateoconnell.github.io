import test from 'node:test';
import assert from 'node:assert/strict';
import { blogRows } from '../public/library.js';

const path = '_posts/2026-11-20-college-football.md';
const post = { path, kind: 'post', title: 'College football', date: '2026-11-20', published: true };
const draft = { id: 'latest', path, title: 'Revised football post', updated: '2026-11-22T14:00:00Z' };

test('the blog library includes published posts and draft-only posts, excluding other content types', () => {
  const rows = blogRows([post, { path: '_research/example.md', kind: 'research' }], [
    { ...draft, path: '_posts/2026-11-22-new-post.md' },
    { ...draft, path: '_pages/about.md' }, { ...draft, path: '_talks/2026-11-22-talk.md' }
  ], '2026-11-22');
  assert.equal(rows.length, 2);
  assert.equal(rows[0].status, 'Private draft');
  assert.equal(rows[1].status, 'Published');
  assert.equal(rows[1].title, post.title);
});

test('multiple drafts share one post row without losing access to older saved versions', () => {
  const older = { ...draft, id: 'older', title: 'Earlier title', updated: '2026-11-21T14:00:00Z' };
  const rows = blogRows([post], [older, draft], '2026-11-22');
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0].drafts.map(d => d.id), ['latest', 'older']);
  assert.equal(rows[0].status, 'Published');
  assert.equal(rows[0].title, draft.title);
  assert.deepEqual(rows[0].file, post);
});

test('hidden, example, invalid-metadata and future-dated posts are not labelled published', () => {
  for (const [change, status] of [
    [{ published: false }, 'Hidden'], [{ example: true }, 'Hidden'],
    [{ metadataError: true }, 'Source file'], [{ date: '2026-11-23' }, 'Future dated']
  ]) assert.equal(blogRows([{ ...post, ...change }], [], '2026-11-22')[0].status, status);
});

test('drafts stay accessible after the corresponding website file is removed', () => {
  const [row] = blogRows([], [{ ...draft, publishedCommit: 'previous-publication' }], '2026-11-22');
  assert.equal(row.status, 'Private draft');
  assert.equal(row.drafts[0].id, draft.id);
  assert.equal(row.file, null);
});
