import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { applyPatches, partialMessage, suggest } from '../lib/assistant.js';
import { writingTurn, writingAction } from '../lib/writing-chat.js';
import { draftPath, loadDraft, updateDraft } from '../lib/drafts.js';
import { blobSha, HttpError } from '../lib/security.js';
import { mergeWritingResult } from '../public/writing-chat.js';

const document = { path: '_posts/2026-11-11-test.md', kind: 'post', fields: { title: 'Draft', date: '2026-11-11', published: false }, body: 'Keep my opening.\n\nChange this sentence.\n\nKeep my ending and $$x_i^2$$.' };
const proposal = (message = 'Here is an edit.', after = 'A better sentence.') => ({ message, edits: [], body_edits: [{ before: 'Change this sentence.', after }] });
const reply = message => ({ message, edits: [], body_edits: [] });
function response(value, status = 'completed', reason) {
  const source = JSON.stringify(value), encoder = new TextEncoder();
  const events = Array.from(source, delta => ({ type: 'response.output_text.delta', delta }));
  events.push({ type: `response.${status}`, response: { status, incomplete_details: reason ? { reason } : null, output: [{ type: 'message', content: [{ type: 'output_text', text: source }] }], usage: { output_tokens: 40 } } });
  return new Response(new ReadableStream({ start(controller) { for (const event of events) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`)); controller.close(); } }), { headers: { 'Content-Type': 'text/event-stream' } });
}
function repository() {
  const id = randomUUID(), files = new Map(); let version = 0;
  files.set(draftPath(id), JSON.stringify({ id, document, source: '', sourceSha: null, assets: [] }) + '\n');
  const config = { drafts: 'private', daily: 50, apiKey: 'test-secret', model: 'gpt-5.4-mini' };
  const github = {
    config, files, id, writes: [],
    head: async () => String(version),
    async read(repo, path) { assert.equal(repo, 'private'); const text = files.get(path); return text === undefined ? null : { sha: blobSha(text), buffer: Buffer.from(text) }; },
    async readJson(repo, path, ref, fallback) { const file = await this.read(repo, path); return file ? JSON.parse(file.buffer.toString()) : fallback; },
    async commit(repo, head, changes) { assert.equal(repo, 'private'); if (head !== String(version)) throw new HttpError(409, 'Concurrent commit'); version++; this.writes.push(changes.map(file => file.path)); for (const file of changes) files.set(file.path, file.content); },
    async writePrivate(path, content, sha) { assert.equal(blobSha(files.get(path)), sha); version++; this.writes.push([path]); files.set(path, content); }
  };
  return github;
}
async function turn(github, prompt, value, options = {}) {
  const loaded = await loadDraft(github, github.id), events = [], requests = [];
  const data = { id: github.id, revision: loaded.revision, prompt, requestId: randomUUID(), ...options.data };
  const result = await writingTurn(github, github.config, data, { signal: options.signal || new AbortController().signal, emit: event => events.push(structuredClone(event)) }, async (url, request) => {
    assert.equal(url, 'https://api.openai.com/v1/responses'); requests.push(JSON.parse(request.body));
    return options.transport ? options.transport(request) : response(value, options.status, options.reason);
  });
  return { result, events, requests, data };
}

test('targeted edits preserve unchanged Markdown and equations and reject ambiguous matches', () => {
  const next = applyPatches(document, proposal());
  assert.equal(next.body, document.body.replace('Change this sentence.', 'A better sentence.'));
  assert.equal(document.body.includes('Change this sentence.'), true);
  assert.throws(() => applyPatches({ ...document, body: 'same same' }, { ...reply('Edit'), body_edits: [{ before: 'same', after: 'new' }] }), /uniquely match/);
  assert.throws(() => applyPatches(document, { ...reply('Edit'), body_edits: [{ before: '', after: 'overwrite' }] }), /ambiguous insertion/);
  assert.throws(() => applyPatches(document, { ...reply('Edit'), edits: [{ field: 'published', value_json: 'true' }] }), /cannot change/);
});

test('stream decoding exposes only the conversational text, including split JSON escapes', () => {
  const message = 'Use "this"\nThen \\theta and 🧮.', source = JSON.stringify({ ...reply(message), edits: [{ field: 'title', value_json: '"private edit"' }] });
  for (let i = 0; i <= source.length; i++) assert.equal(message.startsWith(partialMessage(source.slice(0, i))), true);
  assert.equal(partialMessage(source), message);
  assert.equal(partialMessage('{"message":"a\\u03'), 'a');
  assert.equal(partialMessage('{"message":"a\\u03b8"'), 'aθ');
});

test('questions stream conversational text, persist with their draft, and create no fake edit', async () => {
  const github = repository();
  const { result, events, requests } = await turn(github, 'Can we discuss the opening?', reply('Yes. Who do you want to reach?'));
  assert.equal(events[0].kind, 'checkpoint');
  assert.ok(events.filter(event => event.kind === 'text').length > 2);
  assert.equal(result.draft.writing.messages.length, 2);
  assert.equal(result.draft.writing.proposal, null);
  assert.deepEqual(result.draft.document, document);
  assert.equal(requests.length, 1); assert.equal(requests[0].stream, true); assert.equal(requests[0].store, false);
  assert.equal(requests[0].reasoning.effort, 'low');
  assert.ok(!JSON.stringify(requests[0]).includes('container'));
  assert.ok(github.writes[0].includes('usage.json'), 'allowance and user message are committed together');
  assert.deepEqual(github.writes.at(-1), [draftPath(github.id)], 'reply checkpoints only its private file');
});

test('receiving a reply or recovering a connection preserves typing made during the request', () => {
  const state = { draft: { document: { ...document, body: 'My unsaved typing.' } }, dirty: true, revision: 'old', review: {} };
  const received = { draft: { document: structuredClone(document), writing: { messages: [{ role: 'assistant', content: 'A reply' }] } }, revision: 'new' };
  assert.equal(mergeWritingResult(state, received), false);
  assert.equal(state.draft.document.body, 'My unsaved typing.'); assert.equal(state.dirty, true);
  assert.equal(state.revision, 'new'); assert.equal(state.draft.writing.messages.length, 1); assert.equal(state.review, null);
  state.dirty = false;
  assert.equal(mergeWritingResult(state, { draft: { document: structuredClone(document) }, revision: 'applied' }), true);
  assert.equal(state.draft.document.body, document.body);
  const boundDocument = state.draft.document;
  assert.equal(mergeWritingResult(state, { draft: { document: structuredClone(document) }, revision: 'checkpoint' }), false);
  assert.equal(state.draft.document, boundDocument, 'existing form listeners must keep editing the active document');
  boundDocument.fields.title = 'Typed in the existing form';
  assert.equal(state.draft.document.fields.title, 'Typed in the existing form');
});

test('follow-ups see prior conversation and unaccepted edits; only Apply changes the draft', async () => {
  const github = repository();
  await turn(github, 'Improve the second sentence.', proposal());
  const revised = await turn(github, 'Make that more casual.', proposal('How about this?', 'A more casual sentence.'));
  const input = JSON.stringify(revised.requests[0].input);
  assert.match(input, /Improve the second sentence/); assert.match(input, /Here is an edit/); assert.match(input, /Pending proposal/); assert.match(input, /A better sentence/);
  assert.equal(revised.result.draft.document.body, document.body);
  const question = await turn(github, 'Why that wording?', reply('It uses your original phrasing.'));
  assert.equal(question.result.draft.writing.proposal.id, revised.result.draft.writing.proposal.id);
  const applied = await writingAction(github, { id: github.id, revision: question.result.revision, action: 'apply', proposalId: question.result.draft.writing.proposal.id });
  assert.match(applied.draft.document.body, /A more casual sentence/); assert.equal(applied.draft.writing.proposal, null);
  const next = await turn(github, 'What next?', reply('We can work on the ending.'));
  assert.match(JSON.stringify(next.requests[0].input), /Applied the proposed edit/);
  assert.match(JSON.stringify(next.requests[0].input), /A more casual sentence/);
});

test('token exhaustion saves the partial reply, retains the previous proposal, and never retries the model', async () => {
  const github = repository(); const first = await turn(github, 'Edit this.', proposal());
  const failed = await turn(github, 'Explain more.', reply('Here is what I think so far.'), { status: 'incomplete', reason: 'max_output_tokens' });
  assert.equal(failed.requests.length, 1);
  assert.equal(failed.result.draft.writing.run.status, 'failed');
  assert.match(failed.result.draft.writing.run.error, /token limit/); assert.doesNotMatch(failed.result.draft.writing.run.error, /smaller edit/);
  assert.equal(failed.result.draft.writing.proposal.id, first.result.draft.writing.proposal.id);
  assert.equal(failed.result.draft.writing.messages.at(-2).interrupted, true);
  assert.deepEqual(failed.result.draft.document, document);
  await writingTurn(github, github.config, failed.data, { signal: new AbortController().signal, emit() {} }, () => assert.fail('duplicate request must not spend credits'));
});

test('manual edits invalidate applying an old proposal; discard and clear retain writing', async () => {
  const github = repository(), suggested = await turn(github, 'Edit this.', proposal());
  const edited = await updateDraft(github, { id: github.id, revision: suggested.result.revision, document: { ...document, body: document.body + '\nMy new thought.' } });
  await assert.rejects(writingAction(github, { id: github.id, revision: edited.revision, action: 'apply', proposalId: edited.draft.writing.proposal.id }), /nothing was overwritten/);
  const discarded = await writingAction(github, { id: github.id, revision: edited.revision, action: 'discard', proposalId: edited.draft.writing.proposal.id });
  assert.match(discarded.draft.document.body, /My new thought/);
  assert.match(discarded.draft.writing.messages.at(-1).content, /Discarded/);
  const cleared = await writingAction(github, { id: github.id, revision: discarded.revision, action: 'clear' });
  assert.equal(cleared.draft.writing.messages.length, 0); assert.match(cleared.draft.document.body, /My new thought/);
});

test('an in-progress reply blocks competing saves and messages without another model call', async () => {
  const github = repository(); let finish, checkpoint;
  const entered = new Promise(resolve => { checkpoint = resolve; });
  const pending = turn(github, 'First message', reply('Done'), { transport: async () => { checkpoint(); return new Promise(resolve => { finish = resolve; }); } });
  await entered;
  const loaded = await loadDraft(github, github.id);
  await assert.rejects(updateDraft(github, { id: github.id, revision: loaded.revision, document }), /in progress/);
  await assert.rejects(turn(github, 'Second message', reply('Never')), /in progress/);
  finish(response(reply('Done'))); await pending;
});

test('cancelling preserves conversation and never turns partial output into an edit', async () => {
  const github = repository(), abort = new AbortController();
  const stopped = await turn(github, 'Please edit', proposal(), { signal: abort.signal, transport: async () => { abort.abort(); throw new DOMException('Aborted', 'AbortError'); } });
  assert.equal(stopped.result.draft.writing.run.status, 'stopped');
  assert.equal(stopped.result.draft.writing.messages[0].content, 'Please edit');
  assert.deepEqual(stopped.result.draft.document, document); assert.equal(stopped.result.draft.writing.proposal, null);
});

test('large drafts send targeted edits and bounded history without replaying old PDFs', async () => {
  let request;
  const large = { ...document, body: 'Unchanged text.\n'.repeat(5000) + 'Unique passage.' };
  const changed = await suggest({ apiKey: 'test', model: 'gpt-5.4-mini' }, large, 'Fix the last phrase.', null, async (url, options) => {
    request = JSON.parse(options.body); return response({ ...reply('Fixed that phrase.'), body_edits: [{ before: 'Unique passage.', after: 'Updated passage.' }] });
  }, { messages: Array.from({ length: 50 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', content: `Message ${i}: ${'a'.repeat(3000)}`, attachment: true })), signal: new AbortController().signal });
  assert.equal(request.input.length <= 25, true); assert.equal(request.store, false);
  assert.ok(request.text.format.schema.properties.body_edits); assert.equal(request.text.format.schema.properties.body, undefined);
  assert.equal(request.input.some(item => Array.isArray(item.content) && item.content.some(part => part.type === 'input_file')), false);
  assert.equal(changed.document.body, large.body.replace('Unique passage.', 'Updated passage.'));
});
