import { createHash } from 'node:crypto';
import { HttpError, SITE, SITE_URL, SESSION, STATE, configuration, nonce, seal, unseal, cookies, cookie, session, requireMutation, readJson, validId, equal, blobSha } from '../lib/security.js';
import { GitHub } from '../lib/github.js';
import { schemas, kindForPath } from '../public/schema.js';
import { parseSource, validateDocument } from '../lib/content.js';
import { loadDraft, saveDraft, openDraft, updateDraft, addImage, preparePublish, claimAiRequest } from '../lib/drafts.js';
import { suggest, pdfAttachment } from '../lib/assistant.js';
import { createChat, loadChat, saveChat, deleteChat, websiteSnapshot, sitePath, applySiteProposal, prepareChatPublish, workingFileSha, checkFileExpectations } from '../lib/site-chat.js';
import { startChat, pollChat, stopChat } from '../lib/repository-chat.js';
import { streamChat } from '../lib/chat-stream.js';
import { liveChat } from '../lib/live-chat.js';
import { cleanupDeletedChat } from '../lib/chat-cleanup.js';

const json = (data, status = 200) => Response.json(data, { status, headers: { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'X-Robots-Tag': 'noindex' } });
function redirect(location, values = []) {
  const headers = new Headers({ Location: location, 'Cache-Control': 'no-store' });
  for (const value of values) headers.append('Set-Cookie', value);
  return new Response(null, { status: 303, headers });
}
async function auth(request, route, config) {
  if (request.method !== 'GET') throw new HttpError(405, 'Use GET to sign in.');
  if (route === 'auth/start') {
    const state = nonce(), verifier = nonce();
    const url = new URL('https://github.com/login/oauth/authorize');
    url.search = new URLSearchParams({ client_id: config.clientId, redirect_uri: `${config.origin}/api/auth/callback`, state,
      code_challenge: createHash('sha256').update(verifier).digest('base64url'), code_challenge_method: 'S256' }).toString();
    return redirect(url.toString(), [cookie(STATE, seal({ state, verifier }, 'oauth', config, 600), 600)]);
  }
  const query = new URL(request.url).searchParams;
  const saved = unseal(cookies(request)[STATE], 'oauth', config);
  if (!saved || !equal(saved.state, query.get('state')) || !query.get('code')) throw new HttpError(403, 'Sign-in expired or could not be verified. Start again.');
  let tokenResponse;
  try {
    tokenResponse = await fetch('https://github.com/login/oauth/access_token', { method: 'POST', signal: AbortSignal.timeout(15000), redirect: 'error',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: config.clientId, client_secret: config.clientSecret, code: query.get('code'), code_verifier: saved.verifier, redirect_uri: `${config.origin}/api/auth/callback` }) });
  } catch { throw new HttpError(502, 'GitHub sign-in did not respond. Start again.'); }
  const token = await tokenResponse.json();
  if (!tokenResponse.ok || !token.access_token) throw new HttpError(401, 'GitHub sign-in failed. Start again.');
  const github = new GitHub(token.access_token, config);
  const user = await github.request('/user');
  if (String(user.id) !== config.ownerId) return redirect(`${config.origin}/?error=account`, [cookie(STATE, '', 0), cookie(SESSION, '', 0)]);
  const age = Math.min(Number(token.expires_in) || 28800, 28800);
  return redirect(config.origin, [cookie(STATE, '', 0), cookie(SESSION, seal({ id: user.id, login: user.login, token: token.access_token, csrf: nonce() }, 'session', config, age), age)]);
}
export async function handle(request) {
  let route;
  try {
    const config = configuration();
    const url = new URL(request.url);
    route = url.searchParams.get('route') || url.pathname.replace(/^\/api\/?/, '');
    if (['auth/start', 'auth/callback'].includes(route)) return await auth(request, route, config);
    const current = session(request, config);
    const github = new GitHub(current.token, config);
    if (route === 'session' && request.method === 'GET') {
      const user = await github.request('/user');
      if (String(user.id) !== config.ownerId) throw new HttpError(403, 'This account cannot use the editor.');
      await github.privateRepo();
      return json({ login: user.login, csrf: current.csrf, ai: Boolean(config.apiKey), model: config.model, agentModel: config.agentModel, dailyLimit: config.daily, schemas });
    }
    if (request.method === 'POST') requireMutation(request, current, config);
    else if (request.method !== 'GET') throw new HttpError(405, 'Unsupported method.');
    if (route === 'logout' && request.method === 'POST') {
      const response = json({ ok: true }); response.headers.set('Set-Cookie', cookie(SESSION, '', 0)); return response;
    }
    // Fail closed if private storage is ever made public.
    await github.privateRepo();
    if (request.method === 'GET') {
      if (route === 'chat/events') {
        const { chat } = await loadChat(github, validId(url.searchParams.get('id')));
        return await streamChat(config, chat.run, request.signal, undefined, url.searchParams.get('after'), url.searchParams.get('response'));
      }
      if (route === 'workspace/tree') {
        const tree = await github.tree(SITE, await github.head(SITE));
        return json({ files: tree.entries.filter(item => item.type === 'blob' && ['100644', '100755'].includes(item.mode) && sitePath(item.path)).map(({ path, size }) => ({ path, size })) });
      }
      if (route === 'workspace/preview') {
        const { chat } = await loadChat(github, validId(url.searchParams.get('id')));
        if (!chat.preview) throw new HttpError(404, 'Build a preview in the chat first.');
        const bundle = await github.readJson(config.drafts, `chats/previews/${chat.id}.json`);
        const page = bundle?.pages?.find(item => item.path === url.searchParams.get('path'));
        if (!page) throw new HttpError(404, 'Preview page not found.');
        return new Response(page.html, { headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow',
          'Content-Security-Policy': "sandbox allow-scripts; default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data: https://nateoconnell.com; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'" } });
      }
      if (route === 'chats') return json(await github.readJson(config.drafts, 'chats/index.json', 'main', { chats: [] }));
      if (route === 'chat') return json(await loadChat(github, validId(url.searchParams.get('id'))));
      if (route === 'library') {
        const tree = await github.tree(SITE, await github.head(SITE));
        return json({ files: tree.entries.filter(item => item.type === 'blob' && item.mode === '100644' && kindForPath(item.path)).map(item => ({ path: item.path, kind: kindForPath(item.path) })) });
      }
      if (route === 'drafts') return json(await github.readJson(config.drafts, 'index.json', 'main', { drafts: [] }));
      if (route === 'draft') return json(await loadDraft(github, validId(url.searchParams.get('id'))));
      if (route === 'media') {
        const { draft } = await loadDraft(github, validId(url.searchParams.get('id')));
        const asset = draft.assets.find(item => item.id === url.searchParams.get('asset'));
        if (!asset) throw new HttpError(404, 'Image not found.');
        const file = await github.read(config.drafts, asset.path);
        return json({ mime: asset.mime, base64: file.buffer.toString('base64') });
      }
      throw new HttpError(404, 'Unknown editor action.');
    }
    const data = await readJson(request);
    if (['chat/send', 'chat/poll'].includes(route) && request.headers.get('accept')?.includes('text/event-stream')) {
      return liveChat(flow => route === 'chat/send' ? startChat(github, config, data, flow)
        : pollChat(github, config, validId(data.id), flow), request.signal, config);
    }
    if (route === 'chat/new') return json(await createChat(github));
    if (route === 'chat/delete') return json(await deleteChat(github, data.id, data.revision, chat => cleanupDeletedChat(config, chat)));
    if (route === 'chat/send') return json(await startChat(github, config, data));
    if (route === 'chat/poll') return json(await pollChat(github, config, validId(data.id)));
    if (route === 'chat/stop') return json(await stopChat(github, config, validId(data.id)));
    if (route === 'workspace/file') {
      if (!sitePath(data.path)) throw new HttpError(403, 'This path is outside the website project.');
      const saved = data.id ? await loadChat(github, validId(data.id)) : null;
      const pending = saved?.chat.changes.find(file => file.path === data.path);
      if (pending) return json({ path: data.path, exists: pending.after !== null, sha: workingFileSha(null, saved.chat.changes, data.path), content: pending.after, binary: pending.encoding === 'base64', deleted: pending.after === null, base64: pending.encoding === 'base64' ? pending.after : undefined });
      let file;
      try { file = await github.read(SITE, data.path, 'main', true); }
      catch (error) {
        if (error.status !== 413) throw error;
        const tree = await github.tree(SITE, await github.head(SITE));
        const entry = tree.entries.find(item => item.path === data.path && item.type === 'blob');
        if (!entry) throw error;
        return json({ path: data.path, exists: true, sha: entry.sha, binary: true, url: `https://github.com/${SITE}/blob/main/${data.path.split('/').map(encodeURIComponent).join('/')}` });
      }
      if (!file) return json({ path: data.path, exists: false, sha: null, content: '' });
      const content = file.buffer.toString('utf8');
      if (file.buffer.includes(0) || !Buffer.from(content).equals(file.buffer)) return json({ path: data.path, exists: true, sha: file.sha, binary: true, base64: file.buffer.length <= 1024 * 1024 ? file.buffer.toString('base64') : null, url: `https://github.com/${SITE}/blob/main/${data.path.split('/').map(encodeURIComponent).join('/')}` });
      return json({ path: data.path, exists: true, sha: file.sha, content });
    }
    if (route === 'workspace/edit') {
      const { chat, revision } = await loadChat(github, validId(data.id));
      if (revision !== data.revision) throw new HttpError(409, 'This workspace changed. Reopen it before saving.');
      if (chat.run && !['completed', 'failed', 'cancelled'].includes(chat.run.status)) throw new HttpError(409, 'Stop or finish the active cloud task before editing files directly.');
      if (!Array.isArray(data.edits) || data.edits.length > 200) throw new HttpError(400, 'Provide up to 200 file edits.');
      const snapshot = await websiteSnapshot(github, chat.changes, null, data.edits.map(file => file?.path));
      checkFileExpectations(data.edits, snapshot, chat.changes);
      chat.changes = applySiteProposal(chat.changes, { message: 'Manual file edit', edits: data.edits }, snapshot);
      chat.preview = null;
      if (chat.title === 'New site chat' && data.edits.length) chat.title = `File edits: ${data.edits[0].path}`.slice(0, 100);
      chat.messages.push({ role: 'system', content: `You edited ${data.edits.map(file => file.path).join(', ')} directly in the workspace.` });
      const saved = await saveChat(github, chat, revision);
      return json({ ...saved, edited: data.edits.map(edit => ({ path: edit.path, sha: workingFileSha(snapshot, chat.changes, edit.path) })) });
    }
    if (route === 'chat/discard') {
      const { chat, revision } = await loadChat(github, data.id);
      if (revision !== data.revision) throw new HttpError(409, 'This conversation changed. Reopen it first.');
      if (chat.run && !['completed', 'failed', 'cancelled'].includes(chat.run.status)) throw new HttpError(409, 'Stop the running cloud task before discarding changes.');
      chat.changes = [];
      chat.preview = null;
      chat.messages.push({ role: 'system', content: 'The user discarded all pending changes. Continue from the current public website.' });
      return json(await saveChat(github, chat, revision));
    }
    if (route === 'chat/review') {
      const { chat, revision } = await loadChat(github, data.id);
      if (revision !== data.revision) throw new HttpError(409, 'This conversation changed. Reopen it before reviewing.');
      if (chat.run && !['completed', 'failed', 'cancelled'].includes(chat.run.status)) throw new HttpError(409, 'Wait for the cloud task to finish before publishing.');
      const plan = await prepareChatPublish(github, chat);
      return json({ changes: plan.changes, receipt: seal({ id: chat.id, revision, head: plan.head, hash: plan.hash }, 'site-chat-review', config, 600) });
    }
    if (route === 'chat/publish') {
      const receipt = unseal(data.receipt, 'site-chat-review', config);
      if (!receipt || receipt.id !== data.id) throw new HttpError(409, 'Review the site changes before publishing.');
      const { chat, revision } = await loadChat(github, data.id);
      if (revision !== receipt.revision) throw new HttpError(409, 'The conversation changed after review. Review again.');
      const plan = await prepareChatPublish(github, chat);
      if (plan.head !== receipt.head || plan.hash !== receipt.hash) throw new HttpError(409, 'The website changed after review. Review again before publishing.');
      const commit = await github.commit(SITE, plan.head, plan.files, `Site chat: ${chat.title.replace(/[\r\n]/g, ' ').slice(0, 100)}`);
      chat.changes = [];
      chat.messages.push({ role: 'system', content: `The user published the reviewed changes in commit ${commit}. GitHub Pages deployment has not been verified.` });
      let saved = null, warning = '';
      try { saved = await saveChat(github, chat, revision); } catch { warning = 'The website commit succeeded, but the conversation could not be updated. Start a new chat before making another edit.'; }
      let buildRequested = false;
      try { await github.request(`${github.repo(SITE)}/pages/builds`, 'POST'); buildRequested = true; } catch { warning += ' Check GitHub Pages for deployment status; the build request was not confirmed.'; }
      return json({ commit, commitUrl: `https://github.com/${SITE}/commit/${commit}`, siteUrl: SITE_URL, buildRequested, warning, saved });
    }
    if (route === 'open') return json(await openDraft(github, data));
    if (route === 'save') return json(await updateDraft(github, data));
    if (route === 'upload') return json(await addImage(github, data));
    if (route === 'assist') {
      const { draft, revision } = await loadDraft(github, data.id);
      if (revision !== data.revision) throw new HttpError(409, 'Save or reload your draft before asking the assistant.');
      if (!config.apiKey) throw new HttpError(503, 'The OpenAI key has not been configured. Manual editing is available.');
      if (typeof data.prompt !== 'string' || !data.prompt.trim() || data.prompt.length > 12000) throw new HttpError(400, 'Enter a request under 12,000 characters.');
      pdfAttachment(data.attachment);
      await claimAiRequest(github);
      return json({ ...(await suggest(config, draft.document, data.prompt, data.attachment)), revision });
    }
    if (route === 'review') {
      const { draft, revision } = await loadDraft(github, data.id);
      if (revision !== data.revision) throw new HttpError(409, 'Save or reload the draft before review.');
      const plan = await preparePublish(github, draft);
      const receipt = seal({ id: draft.id, revision, head: plan.head, hash: plan.hash }, 'publish-review', config, 600);
      return json({ receipt, before: draft.source, after: plan.content, paths: plan.files.map(f => f.path), visible: draft.document.fields.published !== false });
    }
    if (route === 'publish') {
      const receipt = unseal(data.receipt, 'publish-review', config);
      if (!receipt || receipt.id !== data.id) throw new HttpError(409, 'Review the changes again before publishing.');
      const { draft, revision } = await loadDraft(github, data.id);
      if (revision !== receipt.revision) throw new HttpError(409, 'The draft changed after review. Review it again.');
      const plan = await preparePublish(github, draft);
      if (plan.head !== receipt.head || plan.hash !== receipt.hash) throw new HttpError(409, 'The website changed after review. Review again before publishing.');
      const commit = await github.commit(SITE, plan.head, plan.files, `Website editor: ${(draft.document.fields.title || schemas[draft.document.kind].label).replace(/[\r\n]/g, ' ').slice(0, 100)}`);
      const previous = draft.source;
      draft.source = plan.content; draft.sourceSha = blobSha(plan.content); draft.previousSource = previous;
      draft.publishedCommit = commit;
      let saved = null, warning = '';
      try { saved = await saveDraft(github, draft, revision); } catch { warning = 'The website commit succeeded, but the private draft could not be updated. Open the website version before making another edit.'; }
      let buildRequested = false;
      try { await github.request(`${github.repo(SITE)}/pages/builds`, 'POST'); buildRequested = true; } catch { warning += ' Check GitHub Pages for deployment status; the explicit build request was not confirmed.'; }
      return json({ commit, commitUrl: `https://github.com/${SITE}/commit/${commit}`, siteUrl: SITE_URL, buildRequested, warning, saved });
    }
    if (route === 'restore') {
      const { draft, revision } = await loadDraft(github, data.id);
      if (revision !== data.revision || !draft.publishedCommit || !Object.hasOwn(draft, 'previousSource')) throw new HttpError(409, 'There is no saved previous version for this draft.');
      const file = await github.read(SITE, draft.document.path);
      if (file.sha !== draft.sourceSha) throw new HttpError(409, 'The website has newer edits. Open its current version before restoring anything.');
      draft.document = draft.previousSource ? await parseSource(draft.document.path, draft.previousSource) : validateDocument({ ...draft.document, fields: { ...draft.document.fields, published: false } });
      return json(await saveDraft(github, draft, revision));
    }
    throw new HttpError(404, 'Unknown editor action.');
  } catch (error) {
    // Never return upstream bodies, tokens, request URLs, or stack traces.
    let reference;
    if (!(error instanceof HttpError)) {
      reference = nonce().slice(0, 12);
      const kind = ['Error', 'TypeError', 'SyntaxError', 'RangeError'].includes(error?.name) ? error.name : 'Error';
      const frames = String(error?.stack || '').split('\n').slice(1).flatMap(line => {
        const match = line.match(/\/(api|lib)\/([A-Za-z0-9_.-]+\.[cm]?js):(\d+):(\d+)/);
        return match ? [`${match[1]}/${match[2]}:${match[3]}:${match[4]}`] : [];
      }).slice(0, 8);
      console.error('editor_request_failed', { reference, kind, frames });
    }
    if (route === 'auth/callback') return new Response('Sign-in could not be completed. Return to the editor and try again.', { status: error.status || 500, headers: { 'Content-Type': 'text/plain', 'Cache-Control': 'no-store' } });
    return json({ error: error instanceof HttpError ? error.message : `The editor hit a server error (reference ${reference}). Your saved conversation and drafts are still available.` }, error instanceof HttpError ? error.status : 500);
  }
}
export default { fetch: handle };
