import { readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { HttpError, SITE, digest } from './security.js';
import { loadChat, saveChat, checkpointChat, websiteSnapshot, applySiteProposal, validateSiteChanges } from './site-chat.js';
import { claimAiRequest } from './drafts.js';
import { pdfAttachment } from './assistant.js';
import { assistantMessages } from './agent-output.js';
import { readEvents } from '../public/event-stream.js';
import { instructions, pollWorkspace as pollLegacy, cancelWorkspace as cancelLegacy } from './hosted-agent.js';
import { usageEvent, recordUsage } from './chat-usage.js';

const ROOT = 'https://api.openai.com/v1';
const WORKSPACE = '/mnt/data/editor-workspace';
const terminal = status => ['completed', 'failed', 'cancelled'].includes(status);
const identifier = value => {
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(value || '')) throw new HttpError(502, 'OpenAI returned an invalid resource identifier.');
  return value;
};
const redact = (value, config) => String(value).replaceAll(config.apiKey || '\0', '[redacted]').replace(/sk-[A-Za-z0-9_.-]+/g, '[redacted]').slice(0, 2000);
const progress = (github, chat, revision) => github.writePrivate ? checkpointChat(github, chat, revision) : saveChat(github, chat, revision);

export async function responseRequest(config, path, method = 'GET', body, transport = fetch, signal) {
  let response;
  const multipart = body instanceof FormData;
  try {
    response = await transport(ROOT + path, { method, redirect: 'error', signal: signal || AbortSignal.timeout(25000),
      headers: { Authorization: `Bearer ${config.apiKey}`, ...(multipart ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: multipart ? body : JSON.stringify(body) }) });
  } catch { throw new HttpError(504, 'OpenAI did not respond. Your conversation and earlier changes are saved.'); }
  if (!response.ok) {
    const error = (await response.json().catch(() => ({}))).error;
    const requestId = response.headers.get('x-request-id');
    const detail = redact(error?.message || response.statusText, config);
    throw Object.assign(new HttpError(response.status, `OpenAI returned HTTP ${response.status}${error?.code ? ` (${redact(error.code, config)})` : ''}: ${detail}`), { requestId, code: error?.code });
  }
  return response;
}
const jsonRequest = async (...args) => (await responseRequest(...args)).json();

async function upload(config, containerId, name, content) {
  const form = new FormData(); form.append('file', new Blob([content]), name);
  const file = await jsonRequest(config, `/containers/${identifier(containerId)}/files`, 'POST', form);
  if (typeof file.path !== 'string' || !/^\/mnt\/data\/[A-Za-z0-9_.-]+$/.test(file.path)) throw new HttpError(502, 'OpenAI returned an unexpected upload path.');
  return file.path;
}

// Save all work before deleting remote resources. Failed cleanup can be retried
// automatically when the conversation is open, without another model request.
async function releaseResources(config, run) {
  const resources = [...new Set([...(run.responseIds || []), run.responseId].filter(Boolean))].map(id => ['responses', id]).concat([['containers', run.containerId]]);
  const results = await Promise.allSettled(resources.filter(([, id]) => id).map(async ([kind, id]) => {
    try { await responseRequest(config, `/${kind}/${identifier(id)}`, 'DELETE'); }
    catch (error) { if (error.status !== 404) throw error; }
  }));
  return results.every(result => result.status === 'fulfilled');
}
async function clean(github, config, saved) {
  const run = saved.chat.run;
  if (!await releaseResources(config, run)) return { ...saved, cleanupWarning: 'Your work is saved. Retrying remote cleanup automatically.' };
  run.cleanupPending = false;
  try { return await progress(github, saved.chat, saved.revision); }
  catch { run.cleanupPending = true; return { ...saved, cleanupWarning: 'Remote cleanup completed. Reconnecting to save its status.' }; }
}
async function finish(github, config, chat, revision, extra = []) {
  chat.run.cleanupPending = true;
  return clean(github, config, await saveChat(github, chat, revision, extra));
}

export async function startWorkspace(github, config, data, options = {}) {
  if (!config.apiKey) throw new HttpError(503, 'Add the OpenAI API key to enable website chat.');
  const loaded = await loadChat(github, data.id), { chat } = loaded;
  if (loaded.revision !== data.revision) throw new HttpError(409, 'This conversation changed. Reopen it first.');
  if (chat.run?.cleanupPending || chat.run?.lookupPending) throw new HttpError(409, 'Use Check progress to finish cleaning up the previous request first.');
  const continuing = options.fromRepository && chat.run?.backend === 'repository' && chat.run.stage === 'ready';
  if (chat.run && !terminal(chat.run.status) && !continuing) throw new HttpError(409, 'A response is already running. Stop it or wait for it to finish.');
  if (chat.messages.length >= 78) throw new HttpError(400, 'This conversation is full. Start a new chat; this one remains saved.');
  if (typeof data.prompt !== 'string' || !data.prompt.trim() || data.prompt.length > 12000) throw new HttpError(400, 'Enter a request under 12,000 characters.');
  const pdf = pdfAttachment(data.attachment);
  const previous = continuing ? chat.run : null;
  if (!continuing) await claimAiRequest(github);
  const remaining = (config.chatOutputTokens || 32000) - (previous?.outputBudgetUsed || 0);
  if (continuing && (previous.step >= config.chatSteps || remaining < 256)) throw new HttpError(429, 'This message reached its execution budget. Your private edits are saved; send a follow-up to continue.');
  const run = { backend: 'responses', key: previous?.key || randomUUID(), status: 'starting', head: previous?.head || null, started: previous?.started || Date.now(), phaseStarted: Date.now(), prompt: previous?.prompt || data.prompt, responseId: null, containerId: null,
    usage: previous?.usage, outputBudgetUsed: previous?.outputBudgetUsed || 0, outputAllowance: Math.min(16000, remaining),
    accountedResponses: previous?.accountedResponses || [], responseIds: previous?.responseIds || [] };
  chat.run = run;
  if (!chat.messages.length) chat.title = data.prompt.replace(/[\r\n]/g, ' ').slice(0, 100);
  if (!continuing) chat.messages.push({ role: 'user', content: data.prompt, attachment: Boolean(pdf) });
  let saved = await progress(github, chat, loaded.revision), responseAttempted = false;
  try {
    const snapshot = await websiteSnapshot(github, chat.changes, run.head);
    run.head = snapshot.head;
    const original = Object.fromEntries([...snapshot.files].map(([path, file]) => [path, file.content]));
    const container = await jsonRequest(config, '/containers', 'POST', { name: `website-${run.key}`, memory_limit: '1g',
      expires_after: { anchor: 'last_active_at', minutes: 20 }, network_policy: config.shellDomains?.length
        ? { type: 'allowlist', allowed_domains: config.shellDomains } : { type: 'disabled' } });
    run.containerId = identifier(container.id);
    usageEvent(chat, 'containers');
    saved = await progress(github, chat, saved.revision);
    // Pending changes overlay the original in prepare(); do not upload a second
    // complete copy of unchanged source on the execution path.
    const source = JSON.stringify({ original, modes: Object.fromEntries([...snapshot.files].map(([path, file]) => [path, file.mode])),
      binaries: Object.fromEntries(snapshot.binaries), lazy_binaries: true, pending: chat.changes, messages: chat.messages,
      assets: snapshot.assets, revision: snapshot.head, repository: SITE });
    const inputPath = await upload(config, run.containerId, 'project-input.json', source);
    const scriptPath = await upload(config, run.containerId, 'workspace.py', await readFile(new URL('../runtime/workspace.py', import.meta.url)));
    const referencePath = pdf ? await upload(config, run.containerId, 'reference.pdf', Buffer.from(data.attachment.base64, 'base64')) : null;
    const setup = `mkdir -p ${WORKSPACE} && cp '${inputPath}' ${WORKSPACE}/project-input.json && cp '${scriptPath}' ${WORKSPACE}/workspace.py${referencePath ? ` && cp '${referencePath}' ${WORKSPACE}/reference.pdf` : ''} && python ${WORKSPACE}/workspace.py prepare ${WORKSPACE}`;
    const guidance = instructions.replaceAll('/workspace/', `${WORKSPACE}/`)
      .replace(`Before your final reply, write that reply to ${WORKSPACE}/result-message.txt, then run python ${WORKSPACE}/workspace.py export`, `After file work, write your final reply to ${WORKSPACE}/result-message.txt, then run python ${WORKSPACE}/workspace.py export ${WORKSPACE}`)
      .replace('Export even when only answering a question; unchanged source yields no new edits.', 'For ordinary conversation, reply directly without using shell or exporting files. For source inspection, edits, or a build, initialize the workspace and export a report before your final answer.')
      + `\nThis is a Responses hosted shell container. Begin with a normal conversational reply. For work involving files, run this initialization exactly once: ${setup}\nThe Python exporter accepts the workspace root as its final argument: python ${WORKSPACE}/workspace.py export ${WORKSPACE}. Existing binary assets start as empty placeholders; these are NOT their actual contents. Unchanged placeholders preserve the public files. To inspect or modify one, retrieve its exact pinned public version and verify the blob SHA in project-input.json before using it. Do not treat an empty placeholder as a broken or empty public file. Pending uploads already contain their actual bytes. A deleted placeholder represents an explicit file deletion.\nHosted shell already includes Python, Node, and Ruby. Do not assume Jekyll or gems are installed. ${config.shellDomains?.length ? `Outbound access is limited to ${config.shellDomains.join(', ')}.` : 'Outbound shell access is disabled. You can edit and inspect source and use web search. If a real build needs missing dependencies, explain that preview needs shell network access; do not invent a rendered preview.'} Keep installs and caches inside the project .codex-tmp directory. Never use sudo.\nA final answer without source work needs no export. After any shell work, export the report to ${WORKSPACE}/outputs/review.json. That report and an optional built preview are the only files imported by the editor.`;
    const input = continuing ? [...previous.nextInput] : chat.messages.filter(message => message.role !== 'system').map(message => ({ role: message.role, content: message.content }));
    if (pdf) input[input.length - 1].content = [{ type: 'input_text', text: data.prompt }, pdf];
    if (continuing) input.push({ role: 'user', content: 'Execution task requested by the website assistant: ' + data.prompt + '. Existing private edits are already in the workspace. Any reference attachment remains in the conversation context; do not assume a reference.pdf file exists unless initialization explicitly copies one. Complete this task and reply to my original request.' });
    run.status = 'submitting';
    saved = await progress(github, chat, saved.revision);
    responseAttempted = true;
    // Background execution survives Vercel/browser disconnects. Consume only
    // response.created here, then reconnect to the retained event stream.
    const response = await responseRequest(config, '/responses', 'POST', { model: config.agentModel, instructions: guidance, input,
      tools: [{ type: 'shell', environment: { type: 'container_reference', container_id: run.containerId } }, { type: 'web_search' }],
      reasoning: { effort: 'medium' }, max_output_tokens: run.outputAllowance, max_tool_calls: 24,
      ...(continuing ? { previous_response_id: previous.responseId } : {}),
      background: true, stream: true, store: true, metadata: { editor_chat: chat.id, request: run.key } });
    run.requestId = response.headers.get('x-request-id');
    for await (const event of readEvents(response.body)) {
      if (event.response?.id) { run.responseId = identifier(event.response.id); break; }
      if (event.type === 'error') throw new HttpError(502, redact(event.message || event.error?.message || 'Response creation failed.', config));
    }
    if (!run.responseId) throw new HttpError(504, 'The response stream closed before its ID was received.');
    run.responseIds.push(run.responseId); usageEvent(chat, 'model_requests');
    run.status = 'in_progress';
    return await progress(github, chat, saved.revision);
  } catch (error) {
    const latest = await loadChat(github, chat.id).catch(() => null);
    if (run.responseId && latest?.chat.run?.responseId === run.responseId) return latest;
    if (latest?.chat.run?.key === run.key && latest.chat.run.backend === 'responses') saved = { ...saved, revision: latest.revision };
    if (run.responseId) {
      // Do not delete an active response when persisting its ID failed.
      try { await responseRequest(config, `/responses/${identifier(run.responseId)}/cancel`, 'POST', {}); }
      catch { run.status = 'cancelling'; run.cleanupPending = true; await saveChat(github, chat, saved.revision).catch(() => {}); throw error; }
    }
    run.status = 'failed';
    run.error = redact(error.message, config);
    if (responseAttempted && !run.responseId && error.status === 504) run.error += ' Creation could not be confirmed. No automatic retry was made; inspect the request in OpenAI before resubmitting.';
    if (!run.containerId && error.status === 504) run.error += ' Any unconfirmed container was configured to expire after 20 minutes of inactivity.';
    run.failure = { source: 'OpenAI request', code: error.code || null, message: run.error, requestId: error.requestId || run.requestId || null, responseId: run.responseId, containerId: run.containerId };
    chat.messages.push({ role: 'system', content: run.error });
    try { return await finish(github, config, chat, saved.revision); }
    catch {
      const cleaned = await releaseResources(config, run);
      throw new HttpError(502, `${run.error} Saving the failed request also failed. ${cleaned ? 'Known remote resources were deleted.' : 'Remote cleanup is incomplete; check OpenAI before retrying.'}`);
    }
  }
}

async function artifacts(config, containerId) {
  const files = []; let after = '';
  // Only two named exports are accepted; inspect bounded pages so ordinary
  // project files cannot crowd a valid report out of the first listing page.
  for (let page = 0; page < 20; page++) {
    const result = await jsonRequest(config, `/containers/${identifier(containerId)}/files?limit=100&order=desc${after ? `&after=${identifier(after)}` : ''}`);
    files.push(...result.data.filter(file => [WORKSPACE + '/outputs/review.json', WORKSPACE + '/outputs/preview.json'].includes(file.path)));
    if (!result.has_more || files.length >= 2) return files;
    after = result.last_id;
  }
  throw new HttpError(502, 'The workspace has too many files to retrieve its result safely.');
}
async function download(config, containerId, file) {
  if (file.bytes > 1800000) throw new HttpError(413, 'The exported result exceeds the editor size limit.');
  const response = await responseRequest(config, `/containers/${identifier(containerId)}/files/${identifier(file.id)}/content`);
  const reader = response.body.getReader(), chunks = []; let size = 0;
  try {
    for (;;) { const { value, done } = await reader.read(); if (done) break; size += value.length;
      if (size > 1800000) throw new HttpError(413, 'The exported result exceeds the editor size limit.'); chunks.push(Buffer.from(value)); }
  } finally { await reader.cancel().catch(() => {}); }
  try { return JSON.parse(Buffer.concat(chunks).toString()); } catch { throw new HttpError(502, 'The exported result was not valid JSON.'); }
}

export async function pollWorkspace(github, config, id) {
  const loaded = await loadChat(github, id), { chat } = loaded, run = chat.run;
  if (run && run.backend !== 'responses') return pollLegacy(github, config, id);
  if (!run) return loaded;
  if (terminal(run.status)) return run.cleanupPending ? clean(github, config, loaded) : loaded;
  if (!run.responseId) {
    if (Date.now() - (run.phaseStarted || run.started) < 180000) return { ...loaded, activity: 'Preparing a temporary workspace for execution…' };
    run.status = 'failed'; run.error = 'The request was interrupted before a response ID was saved. Your earlier changes are intact. No automatic retry was made; inspect the OpenAI request before resubmitting.';
    chat.messages.push({ role: 'system', content: run.error });
    return finish(github, config, chat, loaded.revision);
  }
  const response = run.status === 'cancelling'
    ? await jsonRequest(config, `/responses/${identifier(run.responseId)}/cancel`, 'POST', {})
    : await jsonRequest(config, `/responses/${identifier(run.responseId)}`);
  const replies = assistantMessages(response.output || []);
  if (['queued', 'in_progress'].includes(response.status)) return { ...loaded, liveMessages: replies, activity: 'The assistant is working on your message…' };
  const finalReply = replies.findLast(item => item.phase === 'final_answer')?.content || replies.at(-1)?.content;
  recordUsage(chat, response);
  const extra = [];
  try {
    if (response.status !== 'completed') {
      run.status = response.status === 'cancelled' ? 'cancelled' : 'failed';
      run.failure = { source: 'OpenAI response', code: response.error?.code || response.incomplete_details?.reason || response.status,
        message: redact(response.error?.message || (run.status === 'cancelled' ? 'Response stopped.' : 'The response did not finish.'), config), responseId: run.responseId, requestId: run.requestId };
      run.error = `${run.failure.message} Your earlier proposed changes are still saved.`;
    } else {
      if (!finalReply) throw new HttpError(502, 'OpenAI completed without a conversational reply. Your earlier changes are still saved.');
      const usedShell = (response.output || []).some(item => ['shell_call', 'shell_call_output'].includes(item.type));
      if (usedShell) {
        const files = await artifacts(config, run.containerId), report = files.find(file => file.path.endsWith('/review.json'));
        if (!report) throw new HttpError(502, 'The assistant finished its file work without exporting a reviewable result. Your earlier changes are still saved.');
        const proposal = await download(config, run.containerId, report);
        const baseline = await websiteSnapshot(github, [], run.head);
        const changes = applySiteProposal([], proposal, baseline);
        await validateSiteChanges(changes);
        let preview = null;
        const previewFile = files.find(file => file.path.endsWith('/preview.json'));
        if (previewFile) {
          try {
            const value = await download(config, run.containerId, previewFile);
            if (Array.isArray(value.pages) && value.pages.length <= 12 && value.pages.every(page => typeof page.path === 'string' && typeof page.html === 'string' && typeof page.title === 'string')) {
              extra.push({ path: `chats/previews/${chat.id}.json`, content: JSON.stringify(value) });
              preview = { hash: digest(JSON.stringify(changes)), pages: value.pages.map(({ path, title }) => ({ path, title })) };
            }
          } catch { /* Preserve valid source even when an optional preview fails. */ }
        }
        chat.changes = changes; chat.preview = preview;
      }
      run.status = 'completed';
    }
  } catch (error) {
    run.status = 'failed'; run.error = redact(error.message, config);
    run.failure = { source: 'Workspace result', code: error.code || null, message: run.error, responseId: run.responseId, requestId: error.requestId || run.requestId || null };
  }
  if (finalReply) chat.messages.push({ role: 'assistant', content: finalReply });
  if (run.error) chat.messages.push({ role: 'system', content: run.error });
  return finish(github, config, chat, loaded.revision, extra);
}

export async function cancelWorkspace(github, config, id) {
  const loaded = await loadChat(github, id), run = loaded.chat.run;
  if (run && run.backend !== 'responses') return cancelLegacy(github, config, id);
  if (!run || terminal(run.status)) return loaded;
  if (!run.responseId) throw new HttpError(409, 'The request is still starting. Check progress, then stop it once its response ID is saved.');
  run.status = 'cancelling';
  const saved = await saveChat(github, loaded.chat, loaded.revision);
  await responseRequest(config, `/responses/${identifier(run.responseId)}/cancel`, 'POST', {});
  return saved;
}
