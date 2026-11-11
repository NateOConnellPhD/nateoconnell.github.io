import { markdown } from './markdown.js';
import { readEvents } from './event-stream.js';
import { ChatOutput } from './chat-output.js';
import { createChatView } from './chat-view.js';
import { renderDiff } from './diff.js';

const $ = id => document.getElementById(id);
const node = (tag, text, className) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; };
const base64 = file => new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(new Error('Could not read the file.')); reader.readAsDataURL(file); });

export function createSiteChat({ api, apiStream, run, notice, leaveDraft, aiAvailable, onPublished, onWorkingFiles }) {
  const view = createChatView();
  let current = null, review = null, active = false, inFlight = false, timer = null, filePath = null, fileOriginal = '', fileBinary = false, binaryContent = null;
  let output = new ChatOutput(), outputKey = null, streamAbort = null, streamTimer = null, polling = false, sending = null, savedMessages = '';
  let streamCursor = null, streamResponse = null, liveConnected = false;
  let directAbort = null, deleting = false;
  const running = () => current?.chat.run && !['completed', 'failed', 'cancelled'].includes(current.chat.run.status);
  const needsProgress = () => running() || current?.chat.run?.cleanupPending;
  const fileDirty = () => filePath && !fileBinary && $('file-source').value !== fileOriginal;
  const leaveFile = () => !fileDirty() || confirm('Discard the unsaved file edit?');
  function resetFile() { filePath = null; fileBinary = false; binaryContent = null; fileOriginal = ''; $('workspace-file-panel').hidden = true; }
  function availability() {
    const busy = inFlight || Boolean(directAbort);
    $('chat-send').disabled = !aiAvailable() || busy || Boolean(needsProgress());
    for (const id of ['chat-new', 'workspace-new-file', 'workspace-upload-button']) $(id).disabled = busy;
    for (const button of $('chat-history').querySelectorAll('button')) button.disabled = busy;
    $('chat-review').disabled = !current?.chat.changes.length || Boolean(running());
    $('chat-discard').disabled = !current?.chat.changes.length || Boolean(running());
    $('chat-stop').hidden = !running();
    $('chat-send').hidden = Boolean(running());
    for (const id of ['file-save', 'file-delete', 'file-rename']) $(id).disabled = !filePath || inFlight || Boolean(running());
    $('file-save').disabled ||= fileBinary;
    $('file-rename').disabled ||= fileBinary && !binaryContent;
    $('file-source').disabled = Boolean(running());
  }
  async function refresh() {
    const result = await api('chats');
    const history = $('chat-history'); history.replaceChildren();
    for (const entry of result.chats) {
      const row = node('div', undefined, 'chat-history-row');
      const button = node('button', entry.title, 'chat-history-open'); button.dataset.chatId = entry.id; button.title = entry.title;
      button.setAttribute('aria-current', String(entry.id === current?.chat.id));
      button.disabled = inFlight;
      button.addEventListener('click', () => run(() => openConversation(entry.id)));
      const remove = node('button', 'Delete', 'chat-history-delete');
      remove.type = 'button'; remove.disabled = inFlight;
      remove.setAttribute('aria-label', `Delete chat: ${entry.title}`);
      remove.addEventListener('click', () => run(() => deleteConversation(entry.id)));
      row.append(button, remove); history.append(row);
    }
    if (!result.chats.length) history.append(node('p', 'Your conversations will appear here.', 'small'));
  }
  function show(result) {
    const follow = view.nearBottom() || result?.chat.id !== current?.chat.id;
    if (current?.chat.id && result?.chat.id !== current.chat.id || running() && ['completed', 'failed', 'cancelled'].includes(result?.chat.run?.status)) resetFile();
    current = result; review = null;
    const chat = result?.chat;
    const key = chat?.run?.key || null;
    if (key !== outputKey || !running()) { stopStream(); output = new ChatOutput(); outputKey = key; streamCursor = null; }
    const responseId = chat?.run?.responseId || chat?.run?.sessionId || null;
    if (responseId !== streamResponse) { stopStream(); streamResponse = responseId; streamCursor = null; }
    if (running()) output.snapshot(result.liveMessages);
    $('chat-title').textContent = chat?.messages.length ? chat.title : 'Website chat';
    for (const button of $('chat-history').querySelectorAll('[data-chat-id]')) button.setAttribute('aria-current', String(button.dataset.chatId === chat?.id));
    $('chat-empty').hidden = Boolean(chat?.messages.length);
    renderMessages();
    renderLive();
    const changes = chat?.changes || [];
    onWorkingFiles(changes);
    $('chat-changes').replaceChildren(...changes.map(change => {
      const item = node('li'), button = node('button', change.path, 'quiet'); button.addEventListener('click', () => run(() => openFile(change.path)));
      item.append(button, node('span', ` — ${change.after === null ? 'Delete' : change.beforeSha === null ? 'Create' : 'Update'}: ${change.reason}`)); return item;
    }));
    $('chat-pending').hidden = !changes.length;
    $('chat-count').textContent = `${changes.length} proposed file ${changes.length === 1 ? 'change' : 'changes'}`;
    $('chat-changes-open').hidden = !changes.length;
    $('chat-changes-open').textContent = `${changes.length} proposed ${changes.length === 1 ? 'change' : 'changes'} · Review`;
    $('chat-status').textContent = result?.cleanupWarning || (running() ? (result.outputWarning || result.activity || 'Waiting for the assistant…') : '');
    $('chat-status').dataset.working = String(Boolean(running()));
    const failure = chat?.run?.failure || (chat?.run?.error ? { message: chat.run.error, sessionId: chat.run.sessionId, status: chat.run.status } : null);
    $('chat-error-details').hidden = !failure;
    $('chat-error-data').textContent = failure ? JSON.stringify(failure, null, 2) : '';
    const usage = chat?.usage, last = chat?.run?.usage;
    $('chat-usage').textContent = usage ? 'Recorded usage: ' + usage.model_requests + ' model requests · ' + usage.input_tokens.toLocaleString() + ' input tokens (' +
      usage.cached_input_tokens.toLocaleString() + ' cached) · ' + usage.output_tokens.toLocaleString() + ' output tokens · ' + usage.containers + ' temporary workspaces.' +
      (last ? ' Latest message: ' + last.output_tokens.toLocaleString() + ' output tokens.' : '') +
      (usage.reported_responses < usage.model_requests ? ' Usage is still incomplete for some responses.' : '') : 'Usage will appear after the first response. Token counts are not a dollar spending cap.';
    $('workspace-preview-panel').hidden = !chat?.preview;
    $('workspace-preview-pages').replaceChildren(...(chat?.preview?.pages || []).map(page => { const option = node('option', page.title || page.path); option.value = page.path; return option; }));
    if (chat?.preview) showPreview();
    availability(); schedulePoll(); connectStream(); view.follow(follow);
  }
  function renderMessages() {
    const messages = [...(current?.chat.messages || [])];
    if (sending && !(current?.chat.run?.prompt === sending.prompt && current.chat.run.started >= sending.started)) messages.push({ role: 'user', content: sending.prompt });
    const signature = JSON.stringify(messages);
    if (signature === savedMessages) return;
    savedMessages = signature; $('chat-messages').replaceChildren();
    $('chat-empty').hidden = messages.length > 0;
    for (const message of messages) {
      const item = node('article', undefined, `chat-message chat-${message.role}`);
      item.append(node('p', { user: 'You', assistant: 'Website assistant', system: 'Update' }[message.role], 'eyebrow'));
      const content = node('div', undefined, 'chat-message-body');
      if (message.role === 'assistant') markdown(content, message.content);
      else if (message.role === 'system' && message.content === current?.chat.run?.error) {
        content.append(node('p', current.chat.run.status === 'cancelled' ? 'Response stopped. Your saved changes are still available.' : 'The assistant couldn’t complete this response. Your conversation and earlier changes are saved.'));
        const details = node('button', 'View error details', 'quiet');
        details.addEventListener('click', () => { $('chat-details').open = true; $('chat-error-details').open = true; $('chat-check').focus(); });
        content.append(details);
      } else content.append(node('p', message.content));
      item.append(content);
      if (message.attachment) item.append(node('p', 'Reference PDF was supplied for this message only.', 'small'));
      $('chat-messages').append(item);
    }
  }
  function renderLive() {
    const follow = view.nearBottom();
    const container = $('chat-live'), messages = output.messages();
    const keep = new Set(messages.map(message => message.id));
    for (const child of [...container.children]) if (!keep.has(child.dataset.message)) child.remove();
    for (const [index, message] of messages.entries()) {
      let row = [...container.children].find(child => child.dataset.message === message.id);
      if (!row) {
        row = node('article', undefined, 'chat-message chat-assistant'); row.dataset.message = message.id;
        row.append(node('p', 'Website assistant', 'eyebrow'), node('div', '', 'chat-message-body chat-live-text')); container.append(row);
      }
      if (container.children[index] !== row) container.insertBefore(row, container.children[index] || null);
      if (row.lastElementChild.textContent !== message.content) row.lastElementChild.textContent = message.content;
    }
    view.follow(follow);
  }
  function stopStream() { clearTimeout(streamTimer); streamTimer = null; liveConnected = false; streamAbort?.abort(); streamAbort = null; }
  async function connectStream() {
    if (deleting) return;
    if (directAbort || current?.chat.run?.transport === 'foreground') return;
    if (!active || document.hidden || !running() || !(current?.chat.run.responseId || current?.chat.run.sessionId) || streamAbort || streamTimer) return;
    const id = current.chat.id, key = outputKey, responseId = streamResponse, abort = new AbortController(); streamAbort = abort;
    try {
      const response = await fetch(`/api/chat/events?id=${encodeURIComponent(id)}&response=${encodeURIComponent(responseId)}${streamCursor === null ? '' : `&after=${streamCursor}`}`, { credentials: 'same-origin', cache: 'no-store', signal: abort.signal });
      if (response.status === 204) { await checkProgress(); return; }
      if (!response.ok || !response.body) throw new Error('Live connection unavailable');
      for await (const event of readEvents(response.body)) {
        if (current?.chat.id !== id || outputKey !== key || streamResponse !== responseId || abort.signal.aborted) break;
        if (Number.isSafeInteger(event.cursor)) streamCursor = event.cursor;
        if (event.kind === 'connected') { liveConnected = true; schedulePoll(); }
        else if (event.kind === 'text' || event.kind === 'message') { output.event(event); renderLive(); }
        else if (event.kind === 'status') $('chat-status').textContent = event.text;
        else if (event.kind === 'settle') { await checkProgress(); break; }
      }
    } catch {
      if (!abort.signal.aborted && current?.chat.id === id && running()) $('chat-status').textContent = 'Live connection interrupted. Checking saved replies…';
    }
    finally {
      if (streamAbort === abort) {
        streamAbort = null; liveConnected = false; schedulePoll();
        if (running() && active && !document.hidden) streamTimer = setTimeout(() => { streamTimer = null; connectStream(); }, 2000);
      }
    }
  }
  function showPreview() { $('workspace-preview').src = `/api/workspace/preview?id=${encodeURIComponent(current.chat.id)}&path=${encodeURIComponent($('workspace-preview-pages').value)}`; }
  function schedulePoll() {
    clearTimeout(timer);
    if (directAbort || deleting) return;
    if (needsProgress() && active && !document.hidden) timer = setTimeout(checkProgress,
      ['ready', 'tools'].includes(current?.chat.run?.stage) ? 0 : liveConnected ? 30000 : 2000);
  }
  async function streamAction(route, data) {
    const abort = new AbortController(); directAbort = abort;
    clearTimeout(timer); stopStream(); availability();
    try {
      return await apiStream(route, data, event => {
        if (directAbort !== abort || current?.chat.id !== data.id) return;
        if (event.kind === 'state') show(event.result);
        else if (event.kind === 'text' || event.kind === 'message') { output.event(event); renderLive(); $('chat-status').textContent = ''; }
        else if (event.kind === 'status') $('chat-status').textContent = event.text;
      }, abort.signal);
    } finally { if (directAbort === abort) directAbort = null; availability(); }
  }
  async function checkProgress() {
    if (deleting) return;
    if (polling || directAbort || !current) { schedulePoll(); return; }
    const id = current.chat.id, key = current.chat.run?.key; polling = true;
    try { const result = await streamAction('chat/poll', { id }); if (current?.chat.id === id && current.chat.run?.key === key) show(result); }
    catch (error) { if (current?.chat.id === id) $('chat-status').textContent = error.message + ' Reconnecting automatically…'; }
    finally { polling = false; schedulePoll(); }
  }
  async function activate() {
    if (!(await leaveDraft())) return false;
    active = true; $('site-chat').hidden = false; $('document').hidden = true;
    $('app').classList.add('chat-mode'); view.conversations(false);
    $('site-chat-nav').setAttribute('aria-pressed', 'true');
    await refresh(); availability(); schedulePoll(); connectStream(); view.resize(); return true;
  }
  function hide() { active = false; clearTimeout(timer); stopStream(); $('site-chat').hidden = true; $('site-chat-nav').setAttribute('aria-pressed', 'false'); $('app').classList.remove('chat-mode'); view.project(false, false); }
  async function send() {
    if (inFlight || needsProgress()) return;
    const prompt = $('chat-prompt').value.trim();
    if (!prompt) return;
    const file = $('chat-reference').files[0]; let attachment;
    if (file?.size > 1500000) { notice('Reference PDFs must be smaller than 1.5 MB.', true); return; }
    const started = Date.now();
    inFlight = true; sending = { prompt, started };
    $('chat-prompt').value = ''; $('notice').hidden = true;
    view.resize();
    renderMessages(); availability();
    $('chat-status').textContent = 'Sending your message…';
    view.jump();
    try {
      if (file) attachment = { base64: await base64(file) };
      if (fileDirty()) { await saveFiles([{ path: filePath, content: $('file-source').value, reason: 'Saved before the chat request' }]); fileOriginal = $('file-source').value; }
      if (!current) show({ chat: { id: crypto.randomUUID(), title: 'New site chat', messages: [], changes: [] }, revision: null });
      const result = await streamAction('chat/send', { id: current.chat.id, revision: current.revision, prompt, attachment });
      sending = null; show(result);
      if ($('chat-reference').files[0] === file) $('chat-reference').value = '';
      view.attachment();
      await refresh();
    } catch (error) {
      // A request can reach the server even when its response is lost. Reload
      // the saved session instead of starting another paid task automatically.
      if (current) { try { show(await api(`chat?id=${encodeURIComponent(current.chat.id)}`)); } catch { /* Keep the last confirmed saved state. */ } }
      const accepted = current?.chat.run?.prompt === prompt && current.chat.run.started >= started;
      if (!accepted && !$('chat-prompt').value) $('chat-prompt').value = prompt;
      if (!accepted && current?.revision === null) show(null);
      notice(error.message, true);
    }
    finally { inFlight = false; sending = null; renderMessages(); availability(); schedulePoll(); connectStream(); view.resize(); $('chat-prompt').focus(); }
  }
  function renderChange(change) {
    const section = node('section', undefined, 'chat-change');
    section.append(node('h3', change.title), node('p', `${change.after === null ? 'Delete' : change.before === null ? 'Create' : 'Update'} ${change.path}`, 'small'), node('p', change.reason));
    if (change.fields.length) {
      const list = node('ul');
      for (const field of change.fields) list.append(node('li', `${field.name}: ${JSON.stringify(field.before)} → ${JSON.stringify(field.after)}`));
      section.append(list);
    }
    if (change.encoding === 'base64') { section.append(node('p', 'Binary file update. Its bytes will be published with this change set.', 'small')); return section; }
    if (change.path.endsWith('.md') && change.after !== null) {
      const preview = node('details'); preview.append(node('summary', 'Read proposed content'));
      const body = node('div', undefined, 'prose'); markdown(body, change.after.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '')); preview.append(body); section.append(preview);
    }
    section.append(renderDiff(change.before, change.after)); return section;
  }
  $('site-chat-nav').addEventListener('click', () => run(activate));
  $('chat-new').addEventListener('click', () => run(async () => {
    if (!leaveFile()) return;
    if ($('chat-prompt').value.trim() && !confirm('Discard the unsent message and start a new chat? Saved conversations are kept.')) return;
    if (!(await activate())) return;
    show(null); $('chat-prompt').value = ''; $('chat-reference').value = ''; view.attachment(); view.resize(); $('chat-prompt').focus();
  }));
  async function openConversation(id) {
    if (!leaveFile()) return;
    if ($('chat-prompt').value.trim() && !confirm('Discard the unsent message and open this saved conversation?')) return;
    if (!(await activate())) return;
    show(await api(`chat?id=${encodeURIComponent(id)}`)); $('chat-prompt').value = ''; $('chat-reference').value = '';
    view.attachment(); view.resize(); view.jump();
  }
  async function deleteConversation(id) {
    if (inFlight || directAbort) return;
    const isCurrent = id === current?.chat.id;
    inFlight = true; deleting = true; clearTimeout(timer); stopStream(); availability();
    try {
      const target = await api(`chat?id=${encodeURIComponent(id)}`);
      const task = target.chat.run;
      if (task && !['completed', 'failed', 'cancelled'].includes(task.status)) throw new Error('This response is still running. Open the chat and select Stop before deleting it.');
      const count = target.chat.changes.length;
      const pending = count ? ` This also discards ${count} unpublished file ${count === 1 ? 'change' : 'changes'}.` : '';
      const unsaved = isCurrent && (fileDirty() || $('chat-prompt').value.trim() || $('chat-reference').files.length) ? ' Your unsaved file edit, message, or attachment will also be discarded.' : '';
      if (!confirm(`Delete “${target.chat.title}” and its saved conversation and preview?${pending}${unsaved} Your published website will stay as it is.`)) return;
      notice('Deleting chat…');
      await api('chat/delete', { id, revision: target.revision });
      if (isCurrent) {
        show(null); $('chat-prompt').value = ''; $('chat-reference').value = '';
        $('workspace-preview').removeAttribute('src'); $('chat-review-dialog').close();
        view.attachment(); view.resize();
      }
      await refresh(); notice('Chat deleted.');
    } finally { inFlight = false; deleting = false; availability(); schedulePoll(); connectStream(); }
    $('chat-new').focus();
  }
  $('chat-form').addEventListener('submit', event => { event.preventDefault(); send(); });
  $('chat-stop').addEventListener('click', () => run(async () => { directAbort?.abort(); show(await api('chat/stop', { id: current.chat.id })); }));
  $('chat-check').addEventListener('click', checkProgress);
  $('workspace-preview-pages').addEventListener('change', showPreview);
  $('chat-prompt').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !$('chat-send').disabled) { event.preventDefault(); $('chat-form').requestSubmit(); } });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { clearTimeout(timer); stopStream(); }
    else if (active) { connectStream(); if (needsProgress()) checkProgress(); }
  });
  document.querySelectorAll('[data-chat-example]').forEach(button => button.addEventListener('click', () => { $('chat-prompt').value = button.dataset.chatExample; view.resize(); $('chat-prompt').focus(); }));
  $('chat-review').addEventListener('click', () => run(async () => {
    review = await api('chat/review', { id: current.chat.id, revision: current.revision });
    $('chat-review-content').replaceChildren(...review.changes.map(renderChange));
    $('chat-review-dialog').showModal();
  }, 'Preparing site review…'));
  $('chat-publish').addEventListener('click', () => run(async () => {
    if (!review || !current) throw new Error('Review the changes again before publishing.');
    const result = await api('chat/publish', { id: current.chat.id, receipt: review.receipt });
    $('chat-review-dialog').close(); review = null;
    if (result.saved) show(result.saved);
    else show(null);
    notice(result.warning || 'Your reviewed changes were committed. Check the website after GitHub Pages finishes deploying.', Boolean(result.warning), result.commitUrl);
    await refresh(); await onPublished();
  }, 'Publishing reviewed site changes…'));
  $('chat-discard').addEventListener('click', () => run(async () => {
    if (!confirm('Discard all pending changes in this conversation? Your live website stays as it is.')) return;
    show(await api('chat/discard', { id: current.chat.id, revision: current.revision })); resetFile(); await refresh();
  }));
  async function openFile(path) {
    if (!leaveFile()) return;
    if (!(await activate())) return;
    const file = await api('workspace/file', { id: current?.chat.id, path });
    filePath = path; fileBinary = Boolean(file.binary); binaryContent = file.base64 || null; fileOriginal = fileBinary ? '' : file.content || '';
    $('workspace-file-panel').hidden = false; $('file-path').value = path; $('file-source').value = fileOriginal;
    $('file-source').hidden = Boolean(file.binary); $('file-binary').hidden = !file.binary;
    if (file.binary) { $('file-binary-link').href = file.url || `data:application/octet-stream;base64,${file.base64}`; $('file-binary-link').download = path.split('/').pop(); }
    $('file-state').textContent = file.deleted ? 'Pending deletion. Save to restore it.' : 'Changes are private until you publish the workspace.';
    view.project(true); $('workspace-file-panel').scrollIntoView({ block: 'start' });
    availability();
  }
  async function saveFiles(edits) {
    if (!current) show(await api('chat/new', {}));
    show(await api('workspace/edit', { id: current.chat.id, revision: current.revision, edits }));
    await refresh();
  }
  $('file-save').addEventListener('click', () => run(async () => {
    await saveFiles([{ path: filePath, content: $('file-source').value, reason: 'Edited directly' }]);
    fileOriginal = $('file-source').value; $('file-state').textContent = 'File changes saved privately.';
  }));
  $('file-delete').addEventListener('click', () => run(async () => {
    if (!confirm(`Propose deleting ${filePath}? Nothing is deleted publicly until you publish.`)) return;
    await saveFiles([{ path: filePath, content: null, reason: 'Deleted in the file editor' }]);
    filePath = null; fileOriginal = ''; $('file-source').value = ''; $('workspace-file-panel').hidden = true; availability();
  }));
  $('file-rename').addEventListener('click', () => run(async () => {
    const destination = prompt('New project path (including the filename)', filePath); if (!destination || destination === filePath) return;
    const existing = await api('workspace/file', { id: current?.chat.id, path: destination });
    if (existing.exists) throw new Error('That destination already exists. Choose another path.');
    await saveFiles([{ path: destination, content: fileBinary ? binaryContent : $('file-source').value, encoding: fileBinary ? 'base64' : 'utf8', reason: `Moved from ${filePath}` }, { path: filePath, content: null, reason: `Moved to ${destination}` }]);
    filePath = destination; fileOriginal = $('file-source').value; $('file-path').value = destination;
  }));
  $('workspace-new-file').addEventListener('click', () => run(async () => {
    const path = prompt('New file path within the website project', 'new-page.html'); if (path) await openFile(path);
  }));
  $('workspace-upload-button').addEventListener('click', () => $('workspace-upload').click());
  $('workspace-upload').addEventListener('change', event => { const file = event.target.files[0]; if (!file) return; run(async () => {
    if (file.size > 1024 * 1024) throw new Error('This upload supports files up to 1 MB. Existing larger files remain in the repository.');
    const path = prompt('Save this file at which project path?', `assets/${file.type.startsWith('image/') ? 'images' : 'files'}/${file.name}`); if (!path) return;
    const existing = await api('workspace/file', { id: current?.chat.id, path });
    if (existing.exists && !confirm(`Replace ${path} in the private working changes?`)) return;
    await saveFiles([{ path, content: await base64(file), encoding: 'base64', reason: 'Uploaded in the online workspace' }]);
    await openFile(path); event.target.value = '';
  }); });
  window.addEventListener('beforeunload', event => { if (inFlight || $('chat-prompt').value.trim() || filePath && !fileBinary && $('file-source').value !== fileOriginal) { event.preventDefault(); event.returnValue = ''; } });
  show(null);
  return { activate, hide, refresh, availability, openFile, isActive: () => active };
}
