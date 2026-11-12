import { markdown } from './markdown.js';
import { renderDiff } from './diff.js';
import { schemas } from './schema.js';

const $ = id => document.getElementById(id);
const el = (tag, text, className) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; };
const encode = file => new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(new Error('Could not read the PDF.')); reader.readAsDataURL(file); });
export function mergeWritingResult(state, result) {
  const previous = state.draft.document;
  const changed = JSON.stringify(previous) !== JSON.stringify(result.draft.document);
  state.draft = result.draft; state.revision = result.revision; state.review = null;
  // Field controls retain this object in their input listeners. Keep it when
  // only conversation metadata changed, or when typing is still unsaved.
  if (state.dirty || !changed) state.draft.document = previous;
  return !state.dirty && changed;
}
export function createWritingChat({ api, stream, current, receive, save, available, notice, locked }) {
  let busy = false, abort = null, pending = null, partial = '', stopped = false, message = '';
  const scroll = $('writing-scroll');
  function controls() {
    $('ask').disabled = busy || locked() || !available(); $('ask').hidden = busy;
    $('writing-stop').hidden = !busy || !abort; $('writing-new').disabled = busy || locked();
    for (const id of ['save', 'review', 'restore', 'image-button', 'image-file']) $(id).disabled = busy || locked();
    document.querySelectorAll('[data-image-action]').forEach(node => { node.disabled = busy || locked(); });
    const proposal = current().draft?.writing?.proposal;
    const stale = proposal && JSON.stringify(current().draft.document) !== JSON.stringify(proposal.before);
    $('apply').disabled = busy || locked() || Boolean(stale); $('discard').disabled = busy || locked();
    $('suggestion-state').textContent = stale ? 'Your draft has changed since this proposal. Ask the chat to update it against your current writing.' : 'Apply this edit to your private draft when ready. Publishing is a separate step.';
    $('ai-status').textContent = message;
  }
  function render() {
    const follow = scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop < 100;
    const draft = current().draft, messages = draft?.writing?.messages || [], list = $('writing-messages');
    list.replaceChildren();
    function row(role, content, interrupted = false) {
      const item = el('article', undefined, `writing-message writing-${role}`);
      item.append(el('p', role === 'user' ? 'You' : role === 'assistant' ? 'GPT' : 'Draft update', 'writing-speaker'));
      const body = el('div');
      if (role === 'assistant') markdown(body, content);
      else body.textContent = content;
      item.append(body);
      if (interrupted) item.append(el('p', 'Partial reply · no edits from this response were applied', 'small'));
      list.append(item);
    }
    for (const item of messages) { row(item.role, item.content, item.interrupted); if (item.attachment) list.lastElementChild.append(el('p', 'Reference PDF supplied with this message', 'small')); }
    if (pending && !messages.some(item => item.requestId === pending.id)) row('user', pending.prompt);
    $('writing-live').textContent = partial; $('writing-live').hidden = !partial;
    $('writing-empty').hidden = messages.length > 0 || Boolean(pending);
    const proposal = draft?.writing?.proposal;
    $('suggestion').hidden = !proposal;
    $('suggestion-content').replaceChildren();
    if (proposal) {
      const before = proposal.before || draft.document, after = proposal.document;
      for (const [key, spec] of Object.entries(schemas[before.kind].fields)) {
        if (JSON.stringify(before.fields[key]) === JSON.stringify(after.fields[key])) continue;
        const detail = el('details'); detail.append(el('summary', spec.label), renderDiff(typeof before.fields[key] === 'string' ? before.fields[key] : JSON.stringify(before.fields[key] ?? '', null, 2), typeof after.fields[key] === 'string' ? after.fields[key] : JSON.stringify(after.fields[key] ?? '', null, 2))); $('suggestion-content').append(detail);
      }
      if (before.body !== after.body) { const detail = el('details'); detail.open = true; detail.append(el('summary', 'Writing'), renderDiff(before.body, after.body)); $('suggestion-content').append(detail); }
    }
    controls(); if (follow || pending) scroll.scrollTop = scroll.scrollHeight;
  }
  async function recover(id) {
    for (;;) {
      const result = await api(`draft?id=${encodeURIComponent(id)}`);
      if (current().draft?.id !== id) return;
      receive(result); partial = ''; render();
      const run = result.draft.writing?.run;
      if (run?.status !== 'running' || run.expires <= Date.now()) {
        message = run?.status === 'running' ? 'The previous reply was interrupted. Your saved conversation is available; send a message to continue.' : run?.error || '';
        return;
      }
      message = stopped ? 'Stopping the reply and saving the conversation…' : 'Reconnecting to the saved conversation…'; controls();
      await new Promise(resolve => setTimeout(resolve, 1200));
    }
  }
  async function send() {
    if (busy || locked() || !available() || !$('prompt').value.trim()) return;
    const prompt = $('prompt').value.trim(), file = $('reference').files[0], id = current().draft.id;
    const requestId = crypto.randomUUID();
    busy = true; stopped = false; abort = new AbortController(); pending = { id: requestId, prompt }; partial = ''; message = 'Saving your message…';
    $('prompt').value = ''; $('prompt').style.height = 'auto'; render();
    try {
      let attachment;
      if (file) { if (file.size > 1500000) throw new Error('Reference PDFs must be smaller than 1.5 MB.'); attachment = { base64: await encode(file) }; }
      await save(); abort.signal.throwIfAborted();
      const result = await stream('assist', { id, revision: current().revision, requestId, prompt, attachment }, event => {
        if (event.kind === 'checkpoint') { receive(event.result); if ($('reference').files[0] === file) $('reference').value = ''; message = 'GPT is replying…'; render(); }
        if (event.kind === 'text') {
          const follow = scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop < 100;
          partial = event.text; $('writing-live').textContent = partial; $('writing-live').hidden = !partial;
          message = 'GPT is replying…'; $('ai-status').textContent = message;
          if (follow) scroll.scrollTop = scroll.scrollHeight;
        }
      }, abort.signal);
      receive(result); partial = ''; pending = null; message = result.draft.writing?.run?.error || ''; render();
    } catch (error) {
      message = stopped ? 'Stopping the reply…' : error.message;
      try { await recover(id); } catch { message = 'Could not reconnect. Your message has not been sent again. Reopen this saved draft to recover the conversation.'; }
      if (!current().draft?.writing?.messages.some(item => item.requestId === requestId)) {
        if (!$('prompt').value) $('prompt').value = prompt;
        message = stopped ? 'Message stopped before it was sent.' : error.message;
      }
      pending = null; partial = ''; render();
    } finally { busy = false; abort = null; controls(); }
  }
  async function act(action) {
    if (busy || locked()) return;
    if (action === 'clear' && !confirm('Clear this draft’s conversation and pending suggestion? Your writing stays as it is.')) return;
    busy = true; controls();
    try {
      await save();
      const { draft, revision } = current();
      const result = await api('assist/action', { id: draft.id, revision, action, proposalId: draft.writing?.proposal?.id });
      receive(result); message = ''; render();
    } catch (error) { notice(error.message, true); }
    finally { busy = false; controls(); }
  }
  $('writing-form').addEventListener('submit', event => { event.preventDefault(); send(); });
  $('prompt').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send(); } });
  $('prompt').addEventListener('input', () => { $('prompt').style.height = 'auto'; $('prompt').style.height = `${Math.min($('prompt').scrollHeight, 180)}px`; });
  $('writing-stop').addEventListener('click', () => { stopped = true; abort?.abort(); message = 'Stopping the reply…'; controls(); });
  $('writing-new').addEventListener('click', () => act('clear'));
  $('apply').addEventListener('click', () => act('apply'));
  $('discard').addEventListener('click', () => act('discard'));
  return {
    isBusy: () => busy, controls,
    show() {
      pending = null; partial = ''; message = ''; $('prompt').value = ''; $('reference').value = ''; render();
      const run = current().draft?.writing?.run;
      if (run?.status === 'running') {
        busy = true; controls();
        recover(current().draft.id).catch(error => { message = error.message; }).finally(() => { busy = false; render(); });
      }
    }
  };
}
