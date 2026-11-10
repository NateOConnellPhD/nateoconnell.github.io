import { randomUUID } from 'node:crypto';
import { HttpError, validId, SITE, blobSha, digest } from './security.js';
import { validateDocument, parseSource, serialize, newPath, imageUpload } from './content.js';
import { schemas, initialFields } from '../public/schema.js';

export const draftPath = id => `drafts/${validId(id)}.json`;
export async function loadDraft(github, id, ref = 'main') {
  const file = await github.read(github.config.drafts, draftPath(id), ref);
  const draft = JSON.parse(file.buffer.toString());
  if (draft.id !== id || typeof draft.source !== 'string' || !Array.isArray(draft.assets) || draft.assets.length > 12) throw new HttpError(400, 'Invalid saved draft.');
  draft.document = validateDocument(draft.document);
  for (const asset of draft.assets) {
    validId(asset.id);
    const extension = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif', 'image/webp': 'webp' }[asset.mime];
    if (!extension || asset.path !== `media/${id}/${asset.id}.${extension}` || asset.publicPath !== `/assets/images/editor-${asset.id}.${extension}`) throw new HttpError(400, 'Invalid saved image path.');
  }
  return { draft, revision: file.sha };
}
export async function saveDraft(github, draft, expected, extra = []) {
  const repo = github.config.drafts;
  const head = await github.head(repo);
  const current = await github.read(repo, draftPath(draft.id), head, true);
  if ((current?.sha || null) !== expected) throw new HttpError(409, 'This draft changed in another tab. Reload it before saving.');
  const index = await github.readJson(repo, 'index.json', head, { drafts: [] });
  draft.updated = new Date().toISOString();
  const entry = { id: draft.id, path: draft.document.path, title: draft.document.fields.title || schemas[draft.document.kind].label, updated: draft.updated, publishedCommit: draft.publishedCommit || null };
  index.drafts = [entry, ...index.drafts.filter(item => item.id !== draft.id)];
  const content = JSON.stringify(draft, null, 2) + '\n';
  if (Buffer.byteLength(content) > 800000) throw new HttpError(413, 'This draft is too large.');
  await github.commit(repo, head, [
    { path: draftPath(draft.id), content }, { path: 'index.json', content: JSON.stringify(index, null, 2) + '\n' }, ...extra
  ], `Save private draft: ${entry.title.slice(0, 100)}`);
  return { draft, revision: blobSha(content) };
}
export async function openDraft(github, { path, kind, slug, date }) {
  let source = null, document;
  if (path) {
    if (!Object.values(schemas).some(s => s.path === path || (s.folder && path.startsWith(s.folder + '/')))) throw new HttpError(403, 'Unsupported content path.');
    // Parse and validate the exact allowlisted path before requesting its content.
    const { kindForPath } = await import('../public/schema.js');
    if (!kindForPath(path)) throw new HttpError(403, 'Unsupported content path.');
    source = await github.read(SITE, path);
    document = await parseSource(path, source.buffer.toString());
  } else {
    path = newPath(kind, slug, date);
    if (await github.read(SITE, path, 'main', true)) throw new HttpError(409, 'That filename already exists. Open it from your website content.');
    document = validateDocument({ path, kind, fields: initialFields(kind, date), body: '' });
  }
  return saveDraft(github, { id: randomUUID(), document, sourceSha: source?.sha || null, source: source?.buffer.toString() || '', assets: [] }, null);
}
export async function updateDraft(github, data) {
  const { draft, revision } = await loadDraft(github, data.id);
  if (revision !== data.revision) throw new HttpError(409, 'This draft changed. Reload before saving.');
  if (data.document?.path !== draft.document.path || data.document?.kind !== draft.document.kind) throw new HttpError(403, 'A draft cannot change its destination.');
  draft.document = validateDocument(data.document);
  return saveDraft(github, draft, revision);
}
export async function addImage(github, data) {
  const { draft, revision } = await loadDraft(github, data.id);
  if (revision !== data.revision) throw new HttpError(409, 'Save or reload the draft before uploading.');
  if (draft.assets.length >= 12) throw new HttpError(400, 'This draft already has 12 uploaded images.');
  const image = imageUpload(data);
  const id = randomUUID();
  const asset = { id, mime: image.mime, path: `media/${draft.id}/${id}.${image.ext}`, publicPath: `/assets/images/editor-${id}.${image.ext}` };
  draft.assets.push(asset);
  return { ...(await saveDraft(github, draft, revision, [{ path: asset.path, content: image.buffer }])), asset };
}
export async function preparePublish(github, draft) {
  const content = await serialize(draft.document, draft.source, true);
  const head = await github.head(SITE);
  const current = await github.read(SITE, draft.document.path, head, true);
  if ((current?.sha || null) !== draft.sourceSha) throw new HttpError(409, 'The website changed since this draft was started. Open its current version as a new draft and bring over your edits.');
  const files = [{ path: draft.document.path, content }];
  for (const asset of draft.assets) {
    if (content.includes(asset.publicPath)) {
      const file = await github.read(github.config.drafts, asset.path);
      files.push({ path: asset.publicPath.slice(1), content: file.buffer });
    }
  }
  return { head, files, content, hash: digest(content + files.slice(1).map(f => digest(f.content)).join('')) };
}
export async function claimAiRequest(github) {
  // Persist the allowance in private storage; serverless restarts do not reset it.
  const day = new Date().toISOString().slice(0, 10);
  for (let attempt = 0; attempt < 3; attempt++) {
    const head = await github.head(github.config.drafts);
    const usage = await github.readJson(github.config.drafts, 'usage.json', head, { day, count: 0 });
    const count = usage.day === day ? usage.count : 0;
    if (!Number.isInteger(count) || count < 0 || count >= github.config.daily) throw new HttpError(429, 'The editor’s daily AI request limit has been reached. You can still edit and save manually.');
    try {
      await github.commit(github.config.drafts, head, [{ path: 'usage.json', content: JSON.stringify({ day, count: count + 1 }) + '\n' }], 'Record editor AI request');
      return;
    } catch (error) { if (![409, 422].includes(error.status) || attempt === 2) throw error; }
  }
}
