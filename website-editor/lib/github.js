import { HttpError, SITE } from './security.js';

export class GitHub {
  constructor(token, config, transport = fetch) { this.token = token; this.config = config; this.transport = transport; }
  async request(path, method = 'GET', body) {
    if (!path.startsWith('/') || path.includes('://') || path.includes('..')) throw new HttpError(400, 'Invalid GitHub request.');
    let response;
    try {
      response = await this.transport(`https://api.github.com${path}`, { method, redirect: 'error', signal: AbortSignal.timeout(20000),
        headers: { Authorization: `Bearer ${this.token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body) });
    } catch { throw new HttpError(502, 'GitHub did not respond. Your changes have not been confirmed; reload before retrying.'); }
    if (!response.ok) {
      const errors = { 401: 'GitHub sign-in expired. Please sign in again.', 403: 'GitHub denied access. Check the app permissions or rate limit.', 404: 'The GitHub file or repository was not found.', 409: 'Another edit arrived first. Reload the saved draft before retrying.', 422: 'GitHub could not apply this change. Refresh before trying again.' };
      throw new HttpError(response.status, errors[response.status] || 'GitHub could not complete the request.');
    }
    return response.status === 204 ? {} : response.json();
  }
  repo(name) {
    if (![SITE, this.config.drafts].includes(name)) throw new HttpError(403, 'Repository access is restricted.');
    return `/repos/${name}`;
  }
  async privateRepo() {
    const info = await this.request(this.repo(this.config.drafts));
    if (info.private !== true || info.fork === true || info.owner?.login?.toLowerCase() !== 'nateoconnellphd') throw new HttpError(403, 'Draft storage must be a private, non-fork repository owned by NateOConnellPhD.');
    if (info.default_branch !== 'main') throw new HttpError(409, 'Initialize the private repository with a README on main.');
  }
  async head(repo) { return (await this.request(`${this.repo(repo)}/git/ref/heads/main`)).object.sha; }
  async tree(repo, head) {
    const commit = await this.request(`${this.repo(repo)}/git/commits/${head}`);
    const tree = await this.request(`${this.repo(repo)}/git/trees/${commit.tree.sha}?recursive=1`);
    if (tree.truncated) throw new HttpError(409, 'Repository tree is too large for this editor.');
    return { sha: commit.tree.sha, entries: tree.tree };
  }
  async read(repo, path, ref = 'main', missing = false) {
    const encoded = path.split('/').map(encodeURIComponent).join('/');
    let data;
    try { data = await this.request(`${this.repo(repo)}/contents/${encoded}?ref=${encodeURIComponent(ref)}`); }
    catch (error) { if (missing && error.status === 404) return null; throw error; }
    if (data.type !== 'file' || data.size > 2 * 1024 * 1024) throw new HttpError(413, 'This file cannot be opened in the editor.');
    if (data.encoding !== 'base64') data = { ...data, ...(await this.request(`${this.repo(repo)}/git/blobs/${data.sha}`)) };
    if (data.encoding !== 'base64') throw new HttpError(409, 'GitHub returned an unsupported file format.');
    return { sha: data.sha, buffer: Buffer.from(data.content, 'base64') };
  }
  async readJson(repo, path, ref = 'main', fallback = null) {
    const file = await this.read(repo, path, ref, true);
    return file ? JSON.parse(file.buffer.toString()) : fallback;
  }
  async commit(repo, head, files, message) {
    // The old tree is always retained. Only explicitly listed files change.
    const parent = await this.request(`${this.repo(repo)}/git/commits/${head}`);
    const tree = [];
    for (const file of files) {
      let sha = null;
      if (file.content !== null) sha = (await this.request(`${this.repo(repo)}/git/blobs`, 'POST', {
        content: Buffer.isBuffer(file.content) ? file.content.toString('base64') : Buffer.from(file.content).toString('base64'), encoding: 'base64'
      })).sha;
      tree.push({ path: file.path, mode: '100644', type: 'blob', sha });
    }
    const created = await this.request(`${this.repo(repo)}/git/trees`, 'POST', { base_tree: parent.tree.sha, tree });
    const commit = await this.request(`${this.repo(repo)}/git/commits`, 'POST', { message, tree: created.sha, parents: [head] });
    // A concurrent commit makes this update fail; history is never force-pushed.
    await this.request(`${this.repo(repo)}/git/refs/heads/main`, 'PATCH', { sha: commit.sha, force: false });
    return commit.sha;
  }
}
