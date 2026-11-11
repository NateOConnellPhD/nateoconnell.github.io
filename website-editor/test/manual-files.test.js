import test from 'node:test';
import assert from 'node:assert/strict';
import { contentPath } from '../public/schema.js';
import { uploadPath, createFileActions } from '../public/file-actions.js';
import { newPath } from '../lib/content.js';
import { checkFileExpectations, workingFileSha } from '../lib/site-chat.js';
import { blobSha } from '../lib/security.js';

test('Add content displays the same destination the server uses for each content type', () => {
  for (const [kind, path] of [['post', '_posts/2026-11-11-new-result.md'], ['research', '_research/new-result.md'], ['talk', '_talks/2026-11-11-new-result.md']]) {
    assert.equal(contentPath(kind, 'new-result', '2026-11-11'), path);
    assert.equal(newPath(kind, 'new-result', '2026-11-11'), path);
  }
});
test('uploads suggest media folders without including a local filesystem path', () => {
  assert.equal(uploadPath({ name: 'CV.pdf', type: 'application/pdf' }), 'assets/files/CV.pdf');
  assert.equal(uploadPath({ name: 'Figure 1.png', type: 'image/png' }), 'assets/images/Figure-1.png');
});
test('new files and uploads cannot silently replace an existing or changed destination', () => {
  const snapshot = { files: new Map([['index.html', { sha: blobSha('original') }]]), binaries: new Map() };
  assert.throws(() => checkFileExpectations([{ path: 'index.html', expectedSha: null }], snapshot, []), /already exists/);
  assert.throws(() => checkFileExpectations([{ path: 'index.html', expectedSha: blobSha('older') }], snapshot, []), /changed since/);
  assert.doesNotThrow(() => checkFileExpectations([{ path: 'new.html', expectedSha: null }], snapshot, []));
  assert.doesNotThrow(() => checkFileExpectations([{ path: 'index.html', expectedSha: blobSha('original') }], snapshot, []));
});
test('replacement validation uses current pending bytes, including PDFs and pending deletions', () => {
  const snapshot = { files: new Map(), binaries: new Map([['assets/files/cv.pdf', { sha: blobSha('old-pdf') }]]) };
  const changes = [{ path: 'assets/files/cv.pdf', encoding: 'base64', after: Buffer.from('private-pdf').toString('base64') }];
  const expectedSha = blobSha('private-pdf');
  assert.equal(workingFileSha(snapshot, changes, 'assets/files/cv.pdf'), expectedSha);
  assert.doesNotThrow(() => checkFileExpectations([{ path: 'assets/files/cv.pdf', expectedSha }], snapshot, changes));
  assert.throws(() => checkFileExpectations([{ path: 'assets/files/cv.pdf', expectedSha: blobSha('old-pdf') }], snapshot, changes), /nothing was overwritten/);
  changes[0].after = null;
  assert.doesNotThrow(() => checkFileExpectations([{ path: 'assets/files/cv.pdf', expectedSha: null }], snapshot, changes));
});

test('upload form requires destination review and explicit replacement, including after a stale-file error', async t => {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, {
      value: '', checked: false, files: [], hidden: false, handlers: {},
      addEventListener(type, action) { this.handlers[type] = action; },
      showModal() {}, close() {}, reset() {}, querySelector: () => get('close')
    });
    return nodes.get(id);
  };
  const previous = Object.fromEntries(['document', 'FileReader'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  globalThis.document = { getElementById: get };
  globalThis.FileReader = class { readAsDataURL() { this.result = 'data:application/pdf;base64,cGRm'; this.onload(); } };
  t.after(() => { for (const [key, descriptor] of Object.entries(previous)) { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key]; } });
  let lookups = 0, saves = 0;
  const actions = createFileActions({ lookup: async () => { lookups++; return { exists: true, sha: blobSha('v' + lookups) }; }, openFile: async () => {},
    saveUpload: async edit => { saves++; assert.equal(edit.path, 'assets/files/cv.pdf'); assert.equal(edit.expectedSha, blobSha('v' + lookups)); if (saves === 1) throw new Error('The file changed. Review again.'); return true; }
  });
  actions.open('replace', 'assets/files/cv.pdf');
  get('file-action-upload-input').files = [{ name: 'CV.pdf', type: 'application/pdf', size: 3 }];
  const submit = () => get('file-action-form').handlers.submit({ preventDefault() {} });
  await submit(); assert.equal(lookups, 1); assert.equal(saves, 0);
  assert.match(get('file-action-status').textContent, /REPLACE assets\/files\/cv.pdf/);
  await submit(); assert.equal(saves, 0, 'unchecked replacement must not save');
  get('file-action-replace').checked = true;
  await submit(); assert.equal(saves, 1); assert.match(get('file-action-error').textContent, /file changed/);
  await submit(); assert.equal(get('file-action-replace').checked, false, 'a new file version needs a new confirmation');
  get('file-action-replace').checked = true;
  await submit(); assert.equal(saves, 2);
});
