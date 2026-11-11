import { HttpError, SITE, blobSha } from './security.js';
import { sitePath, applySiteProposal, validateSiteChanges } from './site-chat.js';

const string = { type: 'string' }, integer = { type: 'integer' }, nullable = { type: ['string', 'null'] };
const tool = (name, description, properties) => ({ type: 'function', name, description, strict: true,
  parameters: { type: 'object', additionalProperties: false, properties, required: Object.keys(properties) } });
export const repositoryTools = [
  tool('list_files', 'List current website paths, including private proposed files. Start here to discover files. Empty prefix lists the project. Paginated; does not download file contents.', { prefix: string, offset: integer }),
  tool('read_files', 'Read up to 12 specific current files. Includes private pending edits and a SHA for editing. Long files return a bounded excerpt; read_file_lines retrieves the rest.', { paths: { type: 'array', items: string } }),
  tool('read_file_lines', 'Read a range of lines in a current file; line numbers start at 1. Up to 200 lines per call.', { path: string, start_line: integer, line_count: integer }),
  tool('search_files', 'Literal case-insensitive content search in a path prefix. Searches 12 files per page; follow next_offset until null. Use a specific prefix to avoid unrelated source.', { prefix: string, query: string, offset: integer }),
  tool('edit_file', 'Apply exact, unique text replacements to a file you read. expected_sha must match its current SHA. Efficient for small changes to large files. Saves a private proposal only.', { path: string, expected_sha: string,
    replacements: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { old_text: string, new_text: string }, required: ['old_text', 'new_text'] } } }),
  tool('write_file', 'Create, replace, or delete a file as a private proposal. Supply the current SHA; null means a new file. A null content deletes the file. Prefer edit_file for small replacements.', { path: string, expected_sha: nullable, content: nullable, reason: string }),
  tool('read_conversation', 'Retrieve earlier saved conversation messages when needed. Older messages remain available even when omitted from the immediate model context.', { offset: integer }),
  tool('request_execution', 'Request a temporary coding workspace ONLY when terminal commands, computation, tests, or a rendered preview are needed. Reading/searching/editing any website source uses the other tools and needs no workspace. Explain the concrete execution task.', { task: string })
];

const offset = value => {
  if (!Number.isInteger(value) || value < 0) throw new HttpError(400, 'Invalid page offset.');
  return value;
};
function pathAllowed(path) {
  if (!sitePath(path)) throw new HttpError(403, 'This path is outside the website project.');
  return path;
}

export class RepositoryTools {
  constructor(github, chat, head) { this.github = github; this.chat = chat; this.head = head; this.index = null; this.originals = new Map(); }
  async tree() {
    // Store the promise before awaiting: batched reads share one tree lookup.
    if (!this.index) this.index = this.github.tree(SITE, this.head);
    return this.index;
  }
  async paths(prefix) {
    if (typeof prefix !== 'string' || prefix && !sitePath(prefix.replace(/\/$/, ''))) throw new HttpError(403, 'Invalid website prefix.');
    const tree = await this.tree();
    const paths = new Set(tree.entries.filter(item => item.type === 'blob' && ['100644', '100755'].includes(item.mode) && sitePath(item.path)).map(item => item.path));
    for (const change of this.chat.changes) { if (change.after === null) paths.delete(change.path); else paths.add(change.path); }
    return [...paths].filter(path => path.startsWith(prefix)).sort();
  }
  async original(path) {
    pathAllowed(path);
    if (this.originals.has(path)) return this.originals.get(path);
    const entry = (await this.tree()).entries.find(item => item.path === path);
    if (!entry) return null;
    if (entry.type !== 'blob' || !['100644', '100755'].includes(entry.mode)) throw new HttpError(400, 'Only regular website files can be edited.');
    if (entry.size > 500000) return { ...entry, binary: true, content: null };
    const file = await this.github.blob(SITE, entry.sha);
    const content = file.buffer.toString('utf8');
    const value = { ...entry, content, binary: file.buffer.includes(0) || !Buffer.from(content).equals(file.buffer) };
    if (value.binary) value.content = null;
    this.originals.set(path, value);
    return value;
  }
  async current(path) {
    pathAllowed(path);
    const change = this.chat.changes.find(item => item.path === path);
    if (change) return change.after === null ? null : { sha: blobSha(change.encoding === 'base64' ? Buffer.from(change.after, 'base64') : change.after), content: change.encoding === 'base64' ? null : change.after, binary: change.encoding === 'base64' };
    return this.original(path);
  }
  async read(path, start = 1, count = 200) {
    if (!Number.isInteger(start) || start < 1 || !Number.isInteger(count) || count < 1 || count > 200) throw new HttpError(400, 'Read between 1 and 200 lines.');
    const file = await this.current(path);
    if (!file) return { path, exists: false, sha: null };
    if (file.binary) return { path, exists: true, sha: file.sha, binary: true, note: 'Use the file upload controls to replace binary files; use execution to inspect or generate them.' };
    const lines = file.content.split('\n'), selected = lines.slice(start - 1, start - 1 + count);
    let content = '', used = 0;
    for (const line of selected) {
      if (content.length + line.length + 1 > 24000) break;
      content += (used ? '\n' : '') + line; used++;
    }
    return { path, exists: true, sha: file.sha, content, start_line: start, total_lines: lines.length,
      next_line: start - 1 + used < lines.length ? start + used : null,
      ...(used === 0 && selected.length ? { note: 'This line exceeds the text tool limit. Use execution for this file.' } : {}) };
  }
  async write(path, expected, content, reason) {
    pathAllowed(path);
    const current = await this.current(path);
    if ((current?.sha || null) !== expected) throw new HttpError(409, 'File changed or was not read first. Read its current content and SHA before editing.');
    if (current?.binary && content !== null) throw new HttpError(400, 'Use upload or execution to replace a binary file.');
    const tree = await this.tree(), original = await this.original(path);
    const prior = this.chat.changes.find(item => item.path === path);
    if (prior && prior.beforeSha !== (original?.sha || null)) throw new HttpError(409, 'The published file changed since these private edits began. Resolve that change before editing further.');
    const snapshot = { files: new Map(original && !original.binary ? [[path, original]] : []), binaries: new Map(original?.binary ? [[path, original]] : []),
      occupied: new Set(tree.entries.map(item => item.path)), directories: new Set(tree.entries.filter(item => item.type === 'tree').map(item => item.path)) };
    const changes = applySiteProposal(this.chat.changes, { message: 'Requested edit', edits: [{ path, content, reason }] }, snapshot);
    await validateSiteChanges(changes.filter(change => change.path === path));
    this.chat.changes = changes; this.chat.preview = null;
    return { path, sha: content === null ? null : blobSha(content), saved: 'private proposal', published: false };
  }
  async call(name, args) {
    if (name === 'list_files') {
      const paths = await this.paths(args.prefix), start = offset(args.offset);
      return { files: paths.slice(start, start + 160), next_offset: start + 160 < paths.length ? start + 160 : null };
    }
    if (name === 'read_files') {
      if (!Array.isArray(args.paths) || !args.paths.length || args.paths.length > 12) throw new HttpError(400, 'Read 1 to 12 paths at a time.');
      // Keep aggregate tool output bounded as well as each file excerpt.
      const files = [];
      for (let i = 0; i < args.paths.length; i += 4) files.push(...await Promise.all(args.paths.slice(i, i + 4).map(path => this.read(path))));
      while (JSON.stringify(files).length > 100000) files.pop();
      return { files, remaining_paths: args.paths.slice(files.length) };
    }
    if (name === 'read_file_lines') return this.read(args.path, args.start_line, args.line_count);
    if (name === 'search_files') {
      if (typeof args.query !== 'string' || !args.query.length || args.query.length > 300) throw new HttpError(400, 'Use a literal search string of 1 to 300 characters.');
      const paths = await this.paths(args.prefix), start = offset(args.offset), matches = [], query = args.query.toLowerCase();
      const page = paths.slice(start, start + 12), files = [];
      for (let i = 0; i < page.length; i += 4) files.push(...await Promise.all(page.slice(i, i + 4).map(path => this.current(path))));
      let total = 0;
      for (const [index, path] of page.entries()) {
        const file = files[index];
        if (!file || file.binary) continue;
        file.content.split('\n').forEach((line, i) => { if (line.toLowerCase().includes(query)) { total++; if (matches.length < 40) matches.push({ path, line: i + 1, text: line.slice(0, 400) }); } });
      }
      return { matches, omitted_matches: total - matches.length, next_offset: start + 12 < paths.length ? start + 12 : null };
    }
    if (name === 'write_file') return this.write(args.path, args.expected_sha, args.content, args.reason);
    if (name === 'edit_file') {
      const file = await this.current(args.path);
      if (!file || file.binary) throw new HttpError(400, 'Read an existing text file before editing it.');
      if (!Array.isArray(args.replacements) || !args.replacements.length || args.replacements.length > 20) throw new HttpError(400, 'Provide 1 to 20 exact replacements.');
      let content = file.content;
      for (const edit of args.replacements) {
        if (typeof edit.old_text !== 'string' || !edit.old_text || typeof edit.new_text !== 'string' || content.split(edit.old_text).length !== 2) throw new HttpError(409, 'Replacement text must match exactly once. Read the file and include more surrounding text.');
        content = content.replace(edit.old_text, () => edit.new_text);
      }
      return this.write(args.path, args.expected_sha, content, 'Requested chat edit');
    }
    if (name === 'read_conversation') {
      const start = offset(args.offset), messages = this.chat.messages.slice(start, start + 6);
      return { messages, next_offset: start + messages.length < this.chat.messages.length ? start + messages.length : null };
    }
    throw new HttpError(400, 'Unknown website tool.');
  }
}
