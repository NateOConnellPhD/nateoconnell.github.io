import { randomUUID } from 'node:crypto';
import { HttpError, SITE, validId, blobSha, digest } from './security.js';

const MAX_FILE = 500000, MAX_CONTEXT = 1500000, MAX_CHANGES = 200;
const chatPath = id => `chats/${validId(id)}.json`;

// Repository-wide access. Exclude secrets, local private material and generated
// output, not categories of website code or configuration.
export function sitePath(path, write = false) {
  if (typeof path !== 'string' || !path || path.length > 240 || path.startsWith('/') || /[\\\x00-\x1f\x7f]/.test(path)) return false;
  const parts = path.split('/');
  if (parts.some(part => !part || part === '.' || part === '..' || /^(\.git|\.vercel|\.codex(?:-tmp)?|\.bundle|node_modules|vendor|_site|\.jekyll-cache|context_not_for_upload)$/i.test(part))) return false;
  const filename = parts.at(-1);
  if (/^(\.env(?:\..*)?|credentials(?:\..*)?|id_rsa|id_ed25519)$/i.test(filename) && filename !== '.env.example') return false;
  if (/\.(pem|key|p12|pfx)$/i.test(filename)) return false;
  return true;
}
export const textPath = path => /\.(md|txt|html|xml|yml|yaml|json|js|mjs|cjs|ts|tsx|jsx|css|scss|sass|svg|rb|py|sh|toml|lock|csv|r)$/i.test(path) || /(^|\/)(Gemfile|CNAME|Dockerfile|LICENSE|\.gitignore|\.env\.example)$/.test(path);
function changeBytes(change) {
  if (change.encoding !== 'base64') return sourceText(change.after);
  if (typeof change.after !== 'string' || !/^[A-Za-z0-9+/]*={0,2}$/.test(change.after)) throw new HttpError(400, 'Invalid binary file encoding.');
  const bytes = Buffer.from(change.after, 'base64');
  if (bytes.length > 1024 * 1024) throw new HttpError(413, 'Uploaded or generated binary files must be under 1 MB. Existing larger public files are retained.');
  return bytes;
}
function sourceText(text) {
  if (typeof text !== 'string' || text.includes('\0') || Buffer.byteLength(text) > MAX_FILE) throw new HttpError(413, 'A website file is too large or is not text.');
  return text;
}
export async function websiteSnapshot(github, changes = [], ref = null) {
  const head = ref || await github.head(SITE);
  const tree = await github.tree(SITE, head);
  const entries = tree.entries.filter(item => item.type === 'blob' && ['100644', '100755'].includes(item.mode) && sitePath(item.path) && (textPath(item.path) || !item.path.split('/').at(-1).includes('.')));
  if (entries.length > 800 || entries.reduce((sum, item) => sum + (item.size || 0), 0) > MAX_CONTEXT) throw new HttpError(413, 'The repository exceeds this workspace’s source size limit. No files were changed.');
  const files = new Map(); let bytes = 0;
  for (let i = 0; i < entries.length; i += 6) {
    const batch = await Promise.all(entries.slice(i, i + 6).map(async entry => {
      if (entry.size > MAX_FILE) throw new HttpError(413, `The file ${entry.path} is too large for site chat.`);
      const file = github.blob ? await github.blob(SITE, entry.sha) : await github.read(SITE, entry.path, head);
      return [entry.path, { sha: file.sha, mode: entry.mode, content: sourceText(file.buffer.toString('utf8')) }];
    }));
    for (const [path, file] of batch) { bytes += Buffer.byteLength(file.content); files.set(path, file); }
  }
  if (bytes > MAX_CONTEXT) throw new HttpError(413, 'The website is too large for one chat context. No files were changed.');
  for (const change of changes) if ((tree.entries.find(item => item.path === change.path)?.sha || null) !== change.beforeSha) throw new HttpError(409, `The public version of ${change.path} changed. Start a new chat using the latest website; this chat's changes remain private.`);
  const assets = tree.entries.filter(item => item.type === 'blob' && item.mode === '100644' && /^(assets\/(images|files)\/|Presentations\/)/.test(item.path)).map(item => item.path).slice(0, 300);
  const binaries = new Map(tree.entries.filter(item => item.type === 'blob' && ['100644', '100755'].includes(item.mode) && sitePath(item.path) && !files.has(item.path)).map(item => [item.path, { sha: item.sha, mode: item.mode, binary: true, content: null }]));
  return { head, files, binaries, assets, occupied: new Set(tree.entries.map(item => item.path)), directories: new Set(tree.entries.filter(item => item.type === 'tree').map(item => item.path)) };
}
export function applySiteProposal(changes, proposal, snapshot) {
  if (!proposal || typeof proposal.message !== 'string' || proposal.message.length > 20000 || !Array.isArray(proposal.edits) || proposal.edits.length > MAX_CHANGES) throw new HttpError(502, 'The assistant returned an invalid change set. Nothing was applied.');
  const next = new Map(changes.map(change => [change.path, structuredClone(change)]));
  const seen = new Set();
  for (const edit of proposal.edits) {
    if (!edit || !sitePath(edit.path, true) || seen.has(edit.path) || typeof edit.reason !== 'string' || edit.reason.length > 2000) throw new HttpError(502, 'The assistant proposed an unsupported or duplicate file change. Nothing was applied.');
    seen.add(edit.path);
    const components = edit.path.split('/');
    for (let i = 1; i < components.length; i++) {
      const parent = components.slice(0, i).join('/');
      if (snapshot.occupied.has(parent) && !snapshot.directories?.has(parent)) throw new HttpError(409, 'A parent path is already a file, not a directory.');
    }
    const encoding = edit.encoding === 'base64' ? 'base64' : 'utf8';
    if (edit.content !== null) changeBytes({ encoding, after: edit.content });
    const original = snapshot.files.get(edit.path) || snapshot.binaries?.get(edit.path);
    if (!original && snapshot.occupied.has(edit.path)) throw new HttpError(409, 'A proposed path already exists as an unsupported file or directory.');
    const unchanged = edit.content === null ? !original : original?.sha === blobSha(changeBytes({ encoding, after: edit.content }));
    if (unchanged) next.delete(edit.path);
    else next.set(edit.path, { path: edit.path, encoding, binaryBefore: original?.binary === true, mode: original?.mode || '100644', before: original?.content ?? null, beforeSha: original?.sha || null, after: edit.content, reason: edit.reason });
  }
  const result = [...next.values()].sort((a, b) => a.path.localeCompare(b.path));
  if (result.some(file => file.after !== null && result.some(other => other.path.startsWith(file.path + '/') && other.after !== null))) throw new HttpError(409, 'A file and a directory cannot share the same path.');
  if (result.length > MAX_CHANGES || Buffer.byteLength(JSON.stringify(result)) > 1600000) throw new HttpError(413, 'This update is too large. Split it into smaller changes.');
  return result;
}
async function yamlValue(text) {
  const { parseDocument } = await import('yaml');
  const doc = parseDocument(text, { schema: 'core', uniqueKeys: true, customTags: [] });
  if (doc.errors.length || doc.warnings.length) throw new HttpError(400, 'A proposed file contains invalid or unsupported YAML.');
  return doc.toJS({ maxAliasCount: 0 });
}
async function metadata(path, text) {
  if (text === null) return {};
  if (/\.ya?ml$/.test(path)) return await yamlValue(text);
  if (text.startsWith('---\n') || text.startsWith('---\r\n')) {
    const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
    if (!match) throw new HttpError(400, `Incomplete front matter in ${path}.`);
    const value = await yamlValue(match[1]);
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new HttpError(400, `Expected front matter fields in ${path}.`);
    return value;
  }
  if (/^_(posts|pages|research|talks)\//.test(path)) throw new HttpError(400, `Missing front matter in ${path}.`);
  return {};
}
export async function validateSiteChanges(changes) {
  const summaries = [];
  for (const change of changes) {
    if (!sitePath(change.path, true)) throw new HttpError(403, 'This file is outside the website source scope.');
    if (change.after !== null) changeBytes(change);
    if (change.before !== null) sourceText(change.before);
    if (change.encoding === 'base64' || change.binaryBefore) { summaries.push({ ...change, title: change.path, fields: [] }); continue; }
    if (change.path.endsWith('.json') && change.after !== null) {
      try { JSON.parse(change.after); } catch { throw new HttpError(400, `Invalid JSON in ${change.path}.`); }
    }
    const before = await metadata(change.path, change.before), after = await metadata(change.path, change.after);
    const fields = ['title', 'featured', 'order', 'published', 'area', 'kind', 'layout', 'permalink'];
    summaries.push({ ...change, title: after?.title || before?.title || change.path,
      fields: fields.filter(key => JSON.stringify(before?.[key]) !== JSON.stringify(after?.[key])).map(key => ({ name: key, before: before?.[key] ?? null, after: after?.[key] ?? null })) });
  }
  return summaries;
}
function checkChat(chat) {
  validId(chat.id);
  if (!Array.isArray(chat.changes) || chat.changes.length > MAX_CHANGES || !Array.isArray(chat.messages) || chat.messages.length > 80) throw new HttpError(400, 'Invalid saved conversation.');
  for (const change of chat.changes) {
    if (!sitePath(change.path, true) || typeof change.reason !== 'string' || (change.binaryBefore ? !/^[a-f0-9]{40}$/.test(change.beforeSha) : change.beforeSha !== (change.before === null ? null : blobSha(sourceText(change.before))))) throw new HttpError(400, 'Invalid saved website changes.');
    if (change.after !== null) changeBytes(change);
  }
  for (const message of chat.messages) if (!['user', 'assistant', 'system'].includes(message.role) || typeof message.content !== 'string') throw new HttpError(400, 'Invalid saved message.');
  if (Buffer.byteLength(JSON.stringify(chat)) > 1800000) throw new HttpError(413, 'This conversation is full. Publish or discard its changes, then start a new chat.');
  return chat;
}
export async function loadChat(github, id) {
  const file = await github.read(github.config.drafts, chatPath(id));
  const chat = checkChat(JSON.parse(file.buffer.toString()));
  if (chat.id !== id) throw new HttpError(400, 'Invalid saved conversation.');
  return { chat, revision: file.sha };
}
export async function checkpointChat(github, chat, expected) {
  checkChat(chat);
  const content = JSON.stringify(chat) + '\n';
  await github.writePrivate(chatPath(chat.id), content, expected);
  return { chat, revision: blobSha(content) };
}
export async function saveChat(github, chat, expected, extra = []) {
  checkChat(chat);
  const repo = github.config.drafts, head = await github.head(repo);
  const current = await github.read(repo, chatPath(chat.id), head, true);
  if ((current?.sha || null) !== expected) throw new HttpError(409, 'This conversation changed in another tab. Reopen it before continuing.');
  const index = await github.readJson(repo, 'chats/index.json', head, { chats: [] });
  chat.updated = new Date().toISOString();
  const entry = { id: chat.id, title: chat.title, updated: chat.updated, changes: chat.changes.length };
  index.chats = [entry, ...index.chats.filter(item => item.id !== chat.id)];
  const content = JSON.stringify(chat) + '\n';
  await github.commit(repo, head, [{ path: chatPath(chat.id), content }, { path: 'chats/index.json', content: JSON.stringify(index) + '\n' }, ...extra], `Save private site chat: ${chat.title.slice(0, 100)}`);
  return { chat, revision: blobSha(content) };
}
export async function createChat(github) {
  return saveChat(github, { id: randomUUID(), title: 'New site chat', messages: [], changes: [] }, null);
}
export async function deleteChat(github, id, expected) {
  const repo = github.config.drafts, path = chatPath(id), head = await github.head(repo);
  const file = await github.read(repo, path, head, true);
  if (!file) throw new HttpError(404, 'This conversation was already deleted. Refresh the chat history.');
  if (file.sha !== expected) throw new HttpError(409, 'This conversation changed. Reopen it before deleting it.');
  const chat = checkChat(JSON.parse(file.buffer.toString()));
  if (chat.id !== id) throw new HttpError(400, 'Invalid saved conversation.');
  if (chat.run && !['completed', 'failed', 'cancelled'].includes(chat.run.status)) throw new HttpError(409, 'Stop this response and check its progress before deleting the chat.');
  if (chat.run?.cleanupPending || chat.run?.lookupPending) throw new HttpError(409, 'Open this chat and use Check progress to finish remote cleanup before deleting it.');
  const previewPath = `chats/previews/${id}.json`;
  const [index, preview] = await Promise.all([
    github.readJson(repo, 'chats/index.json', head, { chats: [] }),
    github.read(repo, previewPath, head, true)
  ]);
  index.chats = index.chats.filter(entry => entry.id !== id);
  const files = [{ path, content: null }, { path: 'chats/index.json', content: JSON.stringify(index) + '\n' }];
  if (preview) files.push({ path: previewPath, content: null });
  await github.commit(repo, head, files, `Delete private site chat: ${chat.title.replace(/[\r\n]/g, ' ').slice(0, 100)}`);
  return { deleted: id };
}
export async function prepareChatPublish(github, chat) {
  if (!chat.changes.length) throw new HttpError(400, 'There are no proposed website changes to publish.');
  const changes = await validateSiteChanges(chat.changes);
  const head = await github.head(SITE), tree = await github.tree(SITE, head);
  for (const change of changes) {
    const current = tree.entries.find(item => item.path === change.path);
    if (current && (current.type !== 'blob' || !['100644', '100755'].includes(current.mode))) throw new HttpError(409, 'A destination is no longer a regular website file.');
    if ((current?.sha || null) !== change.beforeSha) throw new HttpError(409, `The public version of ${change.path} changed. Your private changes were kept; start a new chat from the latest website.`);
    if (tree.entries.some(item => change.path.startsWith(item.path + '/') && item.type !== 'tree')) throw new HttpError(409, 'A parent path is no longer a directory.');
  }
  const files = changes.map(change => ({ path: change.path, mode: change.mode || '100644', content: change.after === null ? null : changeBytes(change) }));
  return { head, files, changes, hash: digest(JSON.stringify(changes)) };
}
