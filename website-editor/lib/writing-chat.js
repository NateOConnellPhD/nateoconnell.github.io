import { randomUUID } from 'node:crypto';
import { HttpError, digest, validId } from './security.js';
import { loadDraft, saveDraft, saveWritingCheckpoint, nextAiUsage, assertDraftIdle } from './drafts.js';
import { suggest, pdfAttachment } from './assistant.js';

export async function writingTurn(github, config, data, live, transport = fetch) {
  const loaded = await loadDraft(github, data.id), { draft } = loaded;
  const requestId = validId(data.requestId);
  const writing = draft.writing ||= { messages: [], proposal: null, run: null };
  // A reconnect must never submit the same paid request a second time.
  if (writing.messages.some(message => message.requestId === requestId)) return loaded;
  if (loaded.revision !== data.revision) throw new HttpError(409, 'This draft changed. Reopen its saved version before sending.');
  assertDraftIdle(draft);
  if (!config.apiKey) throw new HttpError(503, 'The OpenAI key has not been configured. Manual editing is available.');
  if (typeof data.prompt !== 'string' || !data.prompt.trim() || data.prompt.length > 12000) throw new HttpError(400, 'Enter a message under 12,000 characters.');
  pdfAttachment(data.attachment);
  if (writing.run?.status === 'running') writing.messages.push({ role: 'system', content: 'The previous response was interrupted. Its partial edits were not applied.' });
  const history = [...writing.messages];
  writing.messages.push({ role: 'user', content: data.prompt.trim(), requestId, attachment: Boolean(data.attachment) });
  writing.run = { id: requestId, status: 'running', expires: Date.now() + 90000 };
  let saved = await saveDraft(github, draft, loaded.revision, async head => [await nextAiUsage(github, head)]);
  live.emit({ kind: 'checkpoint', result: saved });
  let partial = '';
  try {
    live.signal.throwIfAborted();
    const result = await suggest(config, draft.document, data.prompt, data.attachment, transport, {
      messages: history, proposal: writing.proposal, signal: live.signal,
      onText(text) { partial = text; live.emit({ kind: 'text', text }); }
    });
    writing.messages.push({ role: 'assistant', content: result.message });
    if (JSON.stringify(result.document) !== JSON.stringify(draft.document)) {
      writing.proposal = { id: randomUUID(), baseline: digest(JSON.stringify(draft.document)), before: draft.document, document: result.document, patch: result.patch };
    }
    writing.run = { id: requestId, status: 'completed', usage: result.usage || null };
  } catch (error) {
    if (partial) writing.messages.push({ role: 'assistant', content: partial, interrupted: true });
    const message = live.signal.aborted
      ? 'Response stopped or connection interrupted. Your conversation and previous proposal are saved; no partial edits were applied.'
      : error instanceof HttpError ? error.message : 'The response connection failed. Your conversation and previous proposal are saved; no partial edits were applied.';
    writing.messages.push({ role: 'system', content: message });
    writing.run = { id: requestId, status: live.signal.aborted ? 'stopped' : 'failed', error: message };
  }
  saved = await saveWritingCheckpoint(github, draft, saved.revision);
  return saved;
}

export async function writingAction(github, data) {
  const { draft, revision } = await loadDraft(github, data.id);
  if (revision !== data.revision) throw new HttpError(409, 'This draft changed. Reload before applying an edit.');
  assertDraftIdle(draft);
  const writing = draft.writing;
  if (data.action === 'clear') {
    draft.writing = { messages: [], proposal: null, run: null };
  } else {
    if (!writing?.proposal || data.proposalId !== writing.proposal.id) throw new HttpError(409, 'This proposed edit is no longer current.');
    if (data.action === 'apply') {
      if (writing.proposal.baseline !== digest(JSON.stringify(draft.document))) throw new HttpError(409, 'You edited the draft after this proposal. Ask the chat to update its proposal against your current text; nothing was overwritten.');
      draft.document = writing.proposal.document;
    } else if (data.action !== 'discard') throw new HttpError(400, 'Unknown writing chat action.');
    writing.messages.push({ role: 'system', content: data.action === 'apply' ? 'Applied the proposed edit to the private draft. It has not been published.' : 'Discarded the proposed edit. The draft is unchanged.' });
    writing.proposal = null;
  }
  return saveDraft(github, draft, revision);
}
