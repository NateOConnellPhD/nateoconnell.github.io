import test from 'node:test';
import assert from 'node:assert/strict';
import { GitHub } from '../lib/github.js';
import { SITE } from '../lib/security.js';

test('immutable blobs are reused across clients and callers cannot mutate the cache', async () => {
  const sha = 'a'.repeat(40); let calls = 0;
  const fetch = async () => { calls++; return Response.json({ encoding: 'base64', content: Buffer.from('original').toString('base64'), size: 8 }); };
  const first = new GitHub('token', {}, fetch), second = new GitHub('other-token', {}, fetch);
  const [a, b] = await Promise.all([first.blob(SITE, sha), second.blob(SITE, sha)]);
  a.buffer.fill(0);
  assert.equal(b.buffer.toString(), 'original');
  assert.equal((await first.blob(SITE, sha)).buffer.toString(), 'original');
  assert.equal(calls, 1);
});
test('different revisions invalidate naturally; moving heads and private content are never cached', async () => {
  let calls = 0;
  const fetch = async url => { calls++; return Response.json(url.includes('/git/ref/') ? { object: { sha: String(calls) } } : { type: 'file', encoding: 'base64', content: Buffer.from(String(calls)).toString('base64'), size: 1 }); };
  const github = new GitHub('token', { drafts: 'NateOConnellPhD/private' }, fetch);
  await github.blob(SITE, 'b'.repeat(40)); await github.blob(SITE, 'c'.repeat(40));
  assert.notEqual(await github.head(SITE), await github.head(SITE));
  assert.notEqual((await github.read(github.config.drafts, 'chat.json')).buffer.toString(), (await github.read(github.config.drafts, 'chat.json')).buffer.toString());
  assert.equal(calls, 6);
});
test('failed reads are not cached and progress uses a single conditional write', async () => {
  let calls = 0, body;
  const github = new GitHub('token', { drafts: 'NateOConnellPhD/private' }, async (url, options) => {
    calls++; body = options.body && JSON.parse(options.body);
    if (calls === 1) return Response.json({}, { status: 502 });
    return Response.json({ encoding: 'base64', content: '', size: 0 });
  });
  await assert.rejects(github.blob(SITE, 'd'.repeat(40)));
  await github.blob(SITE, 'd'.repeat(40));
  await github.writePrivate('chats/id.json', '{}', 'expected-sha');
  assert.equal(calls, 3); assert.equal(body.sha, 'expected-sha'); assert.equal(body.branch, 'main');
});
