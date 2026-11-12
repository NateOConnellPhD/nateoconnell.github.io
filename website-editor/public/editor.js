import { schemas, contentPath } from './schema.js';
import { markdown, linkTarget } from './markdown.js';
import { createSiteChat } from './site-chat.js';
import { liveRequest } from './live-request.js';
import { renderDiff } from './diff.js';
import { createWritingChat, mergeWritingResult } from './writing-chat.js';

const $ = id => document.getElementById(id);
const state = { auth: null, draft: null, revision: null, dirty: false, busy: false, list: 'content', drafts: [], files: [], projectFiles: [], pendingFiles: [], review: null, images: new Map() };
const element = (tag, text, className) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; };
function notice(message, error = false, link) {
  const node = $('notice'); node.replaceChildren(document.createTextNode(message)); node.classList.toggle('error', error); node.hidden = false;
  if (link) { const a = element('a', ' View update ↗'); a.href = link; a.target = '_blank'; a.rel = 'noopener noreferrer'; node.append(a); }
}
async function api(route, data) {
  const response = await fetch(`/api/${route}`, { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(110000),
    ...(data !== undefined ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.auth?.csrf || '' }, body: JSON.stringify(data) } : {}) });
  let result;
  try { result = await response.json(); } catch { throw new Error('The editor could not reach its server. Check the connection and try again.'); }
  if (!response.ok) { const error = new Error(result.error || 'The request could not be completed.'); error.status = response.status; throw error; }
  return result;
}
async function run(action, message = 'Working…') {
  if (state.busy) return;
  if (writingChat.isBusy()) return notice('Stop the writing reply or let it finish before switching or saving. You can keep typing in the draft.', true);
  state.busy = true;
  const disabled = [...document.querySelectorAll('button,input,textarea,select')].map(node => [node, node.disabled]);
  disabled.forEach(([node]) => { node.disabled = true; });
  $('save-state').textContent = message;
  try { await action(); } catch (error) { notice(error.message, true); }
  finally {
    state.busy = false; disabled.forEach(([node, previous]) => { if (node.isConnected) node.disabled = previous; });
    writingChat.controls(); siteChat.availability(); updateSaveState();
  }
}
function updateSaveState() {
  if (!state.draft) return;
  $('save-state').textContent = state.dirty ? 'Unsaved changes' : `Saved privately · ${new Date(state.draft.updated).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}`;
}
function dirty() { state.dirty = true; state.review = null; updateSaveState(); writingChat.controls(); }
async function refreshLists() {
  const [drafts, files, project] = await Promise.all([api('drafts'), api('library'), api('workspace/tree')]);
  state.drafts = drafts.drafts; state.files = files.files; state.projectFiles = project.files; renderList();
}
function renderList() {
  const container = $('file-list'); container.replaceChildren();
  const descriptions = {
    content: 'Edit your existing pages, posts, research and talks using content forms. Changes are saved as private writing drafts before publishing.',
    drafts: 'Resume content you saved in the writing editor. These drafts are separate from the proposed changes saved in each chat.',
    files: 'Browse all source files and media. Use this for layouts, code, images and PDFs. Edits join the current chat’s proposed changes.'
  };
  $('library-description').textContent = descriptions[state.list];
  $('content-actions').hidden = state.list === 'files'; $('source-actions').hidden = state.list !== 'files';
  $('filter').placeholder = state.list === 'files' ? 'Find a source file or upload…' : state.list === 'drafts' ? 'Find a saved draft…' : 'Find a page, post, research entry or talk…';
  const query = $('filter').value.toLocaleLowerCase();
  if (state.list === 'files') {
    const root = { folders: new Map(), files: [] };
    const workingFiles = new Map(state.projectFiles.map(item => [item.path, item]));
    for (const change of state.pendingFiles) workingFiles.set(change.path, { path: change.path, pending: true, deleted: change.after === null });
    for (const item of workingFiles.values()) {
      if (!item.path.toLocaleLowerCase().includes(query)) continue;
      let branch = root; const pieces = item.path.split('/');
      for (const folder of pieces.slice(0, -1)) { if (!branch.folders.has(folder)) branch.folders.set(folder, { folders: new Map(), files: [] }); branch = branch.folders.get(folder); }
      branch.files.push(item);
    }
    const labels = { _pages: 'Pages', _posts: 'Blog posts', _research: 'Research', _talks: 'Talks', _layouts: 'Page layouts', _includes: 'Shared components', _data: 'Site data', assets: 'Images, styles & scripts', 'website-editor': 'Editor application', '.github': 'GitHub configuration' };
    function draw(branch, parent, depth = 0) {
      for (const [name, child] of [...branch.folders].sort(([a], [b]) => a.localeCompare(b))) {
        const details = element('details', undefined, 'project-folder'); details.open = Boolean(query) || depth === 0 && ['_pages', '_research'].includes(name);
        details.append(element('summary', labels[name] || name)); draw(child, details, depth + 1); parent.append(details);
      }
      for (const item of branch.files.sort((a, b) => a.path.localeCompare(b.path))) {
        const button = element('button', item.path.split('/').pop() + (item.deleted ? ' (delete)' : item.pending ? ' •' : '')); button.title = item.path;
        button.addEventListener('click', () => run(() => siteChat.openFile(item.path), 'Opening project file…')); parent.append(button);
      }
    }
    draw(root, container); return;
  }
  const items = state.list === 'drafts' ? state.drafts : state.files;
  let lastGroup = null;
  const ordered = state.list === 'content' ? [...items].sort((a, b) => (a.kind || '').localeCompare(b.kind || '') || a.path.localeCompare(b.path)) : items;
  for (const item of ordered) {
    const title = item.title || (schemas[item.kind].path ? schemas[item.kind].label : item.path.split('/').pop().replace(/\.md$/, '').replace(/^\d{4}-\d{2}-\d{2}-/, '').replaceAll('-', ' '));
    if (!`${title} ${item.path}`.toLocaleLowerCase().includes(query)) continue;
    if (state.list === 'content' && item.kind !== lastGroup) { container.append(element('h3', schemas[item.kind].label, 'content-group')); lastGroup = item.kind; }
    const button = element('button', title);
    button.classList.toggle('active', item.id === state.draft?.id);
    const pending = state.pendingFiles.some(change => change.path === item.path);
    button.append(element('span', state.list === 'drafts' ? `Saved ${new Date(item.updated).toLocaleDateString()}` : pending ? 'Proposed changes in current chat · opens source editor' : schemas[item.kind].label));
    button.append(element('span', item.path, 'content-path'));
    button.addEventListener('click', () => run(async () => {
      if (state.list === 'content' && pending) { await siteChat.openFile(item.path); return; }
      if (!siteChat.leaveFile() || !(await leaveDraft())) return;
      showDraft(state.list === 'drafts' ? await api(`draft?id=${encodeURIComponent(item.id)}`) : await api('open', { path: item.path }));
      await refreshLists();
    }, 'Opening…'));
    container.append(button);
  }
  if (!container.children.length) container.append(element('p', state.list === 'drafts' ? 'No drafts here yet. Start something new or open a page from Website content.' : 'No matching content.', 'small'));
}
async function leaveDraft() {
  if (writingChat.isBusy()) { notice('Stop the writing reply or let it finish before opening another draft.', true); return false; }
  if (!state.dirty) return true;
  if (!confirm('Save this draft before opening something else? Cancel keeps you here.')) return false;
  await save(); return true;
}
function showDraft(result) {
  siteChat.hide();
  $('app').classList.remove('conversations-open'); $('chat-menu').setAttribute('aria-expanded', 'false');
  state.draft = result.draft; state.revision = result.revision; state.dirty = false; state.review = null; state.images.clear();
  $('document').hidden = false;
  $('document-kind').textContent = schemas[state.draft.document.kind].label;
  $('document-destination').textContent = `${state.draft.sourceSha ? 'Updates' : 'Creates'} ${state.draft.document.path} when you publish. Until then, this is a private draft.`;
  $('restore').hidden = !state.draft.publishedCommit || !Object.hasOwn(state.draft, 'previousSource');
  renderFields(); setView('write'); updateSaveState(); writingChat.show();
}
function inputField(key, spec, value, change) {
  const wrap = element('div', undefined, 'field');
  const id = `field-${key}`;
  const label = element('label', spec.label); label.htmlFor = id; wrap.append(label);
  if (spec.type === 'image') {
    wrap.classList.add('image-field');
    const image = element('img'), placeholder = element('p', value ? 'Loading cover image…' : 'No cover image selected.', 'small');
    image.alt = state.draft.document.fields.cover_alt || 'Cover image preview'; image.hidden = true;
    const unavailable = () => { image.hidden = true; placeholder.hidden = false; placeholder.textContent = 'Preview unavailable. You can replace this image below.'; };
    image.addEventListener('load', () => { image.hidden = false; placeholder.hidden = true; });
    image.addEventListener('error', unavailable);
    const preview = element('div', undefined, 'image-field-preview'); preview.append(image, placeholder);
    const input = element('input'); input.type = 'file'; input.accept = 'image/png,image/jpeg,image/webp,image/gif'; input.hidden = true; input.dataset.imageAction = '';
    const choose = element('button', value ? 'Replace cover image' : 'Upload cover image', 'button'); choose.type = 'button'; choose.id = id; choose.dataset.imageAction = '';
    choose.addEventListener('click', () => input.click());
    input.addEventListener('change', () => { const file = input.files[0]; input.value = ''; if (file) run(() => upload(file, key), 'Saving cover image privately…'); });
    const actions = element('div', undefined, 'image-field-actions'); actions.append(choose);
    if (value) {
      const remove = element('button', 'Remove cover image', 'quiet'); remove.type = 'button'; remove.dataset.imageAction = '';
      remove.addEventListener('click', () => run(async () => {
        change('');
        try { await save(); } finally { renderFields(); }
        notice('Cover removed from this draft. Review and publish to update the website.');
      }, 'Removing cover image…'));
      actions.append(remove);
    }
    const help = element('p', 'Appears at the top of the post. Choose a PNG, JPEG, WebP, or GIF. The image stays private until you publish.', 'small'); help.id = `${id}-help`; choose.setAttribute('aria-describedby', help.id);
    wrap.append(preview, actions, input, help);
    if (value) imageResolver(image, value, unavailable);
    return wrap;
  }
  if (spec.type === 'list') {
    wrap.classList.add('field-list'); const values = Array.isArray(value) ? value : [];
    values.forEach((item, index) => {
      const row = element('div', undefined, 'list-item');
      for (const [subkey, subspec] of Object.entries(spec.fields)) row.append(inputField(`${key}-${index}-${subkey}`, subspec, item[subkey], v => { item[subkey] = v; change(values); }));
      const remove = element('button', 'Remove entry', 'quiet'); remove.type = 'button'; remove.addEventListener('click', () => { values.splice(index, 1); change(values); renderFields(); }); row.append(remove); wrap.append(row);
    });
    const add = element('button', '＋ Add entry', 'button'); add.type = 'button'; add.addEventListener('click', () => { values.push({}); change(values); renderFields(); }); wrap.append(add); return wrap;
  }
  const input = element(spec.type === 'long' ? 'textarea' : spec.type === 'select' ? 'select' : 'input');
  input.id = id;
  if (spec.type === 'select') spec.options.forEach(option => { const node = element('option', option); node.value = option; input.append(node); });
  else if (spec.type === 'boolean') { input.type = 'checkbox'; input.checked = Boolean(value ?? spec.default); label.className = 'field-check'; label.prepend(input); }
  else if (['date', 'number'].includes(spec.type)) input.type = spec.type;
  else if (spec.type !== 'long') input.type = 'text';
  if (spec.type === 'long') input.rows = spec.markdown ? 9 : 4;
  if (spec.type !== 'boolean') { input.value = spec.type === 'tags' ? (value || []).join(', ') : value ?? ''; wrap.append(input); }
  input.addEventListener('input', () => {
    change(spec.type === 'boolean' ? input.checked : spec.type === 'number' ? Number(input.value) : spec.type === 'tags' ? input.value.split(',').map(v => v.trim()).filter(Boolean) : input.value);
  });
  if (spec.type === 'tags') wrap.append(element('p', 'Separate topics with commas.', 'small'));
  if (spec.help) wrap.append(element('p', spec.help, 'small'));
  return wrap;
}
function renderFields() {
  const doc = state.draft.document, schema = schemas[doc.kind];
  $('document-title').textContent = doc.fields.title || schema.label;
  $('fields').replaceChildren();
  for (const [key, spec] of Object.entries(schema.fields)) $('fields').append(inputField(key, spec, doc.fields[key], value => {
    doc.fields[key] = value; dirty(); if (key === 'title') $('document-title').textContent = value || 'Untitled';
  }));
  $('body-area').hidden = !schema.body; $('body').value = doc.body || '';
}
async function save() {
  if (!state.draft || !state.dirty) return;
  const sent = JSON.stringify(state.draft.document);
  const result = await api('save', { id: state.draft.id, revision: state.revision, document: JSON.parse(sent) });
  const typedDuringSave = JSON.stringify(state.draft.document) !== sent, document = state.draft.document;
  state.draft = result.draft;
  if (typedDuringSave || JSON.stringify(result.draft.document) === sent) state.draft.document = document;
  else renderFields();
  state.revision = result.revision; state.dirty = typedDuringSave; state.review = null;
  updateSaveState();
  const index = await api('drafts'); state.drafts = index.drafts; renderList();
}
function imageResolver(image, path, unavailable = () => { image.alt += ' (preview unavailable)'; }) {
  const asset = state.draft?.assets.find(item => item.publicPath === path);
  if (asset) {
    if (!state.images.has(asset.id)) state.images.set(asset.id, api(`media?id=${state.draft.id}&asset=${asset.id}`).then(data => `data:${data.mime};base64,${data.base64}`));
    state.images.get(asset.id).then(src => { if (image.isConnected) image.src = src; }).catch(unavailable);
  } else if (/^\/assets\/images\/[A-Za-z0-9/_ .-]+$/.test(path)) image.src = `https://nateoconnell.com${path}`;
  else unavailable();
}
function preview(doc, container) {
  container.replaceChildren();
  const schema = schemas[doc.kind];
  if (schema.body) {
    container.append(element('h1', doc.fields.title || schema.label));
    if (doc.fields.description || doc.fields.summary) container.append(element('p', doc.fields.description || doc.fields.summary));
    if (doc.fields.cover) { const img = element('img'); img.alt = doc.fields.cover_alt || ''; container.append(img); imageResolver(img, doc.fields.cover); }
    markdown(container, doc.body, imageResolver);
  } else for (const [key, spec] of Object.entries(schema.fields)) {
    const value = doc.fields[key]; if (value === '' || value === undefined) continue;
    container.append(element('h2', spec.label));
    if (spec.markdown) markdown(container, value, imageResolver);
    else if (Array.isArray(value)) value.forEach(item => { const div = element('div', undefined, 'metadata-preview'); for (const [name, entry] of Object.entries(item)) if (typeof entry !== 'boolean') div.append(element('p', `${spec.fields?.[name]?.label || name}: ${entry}`)); container.append(div); });
    else container.append(element('p', String(value)));
  }
}
function setView(view) {
  $('write-pane').hidden = view !== 'write'; $('preview-pane').hidden = view !== 'preview';
  $('write-tab').setAttribute('aria-pressed', String(view === 'write')); $('preview-tab').setAttribute('aria-pressed', String(view === 'preview'));
  if (view === 'preview') preview(state.draft.document, $('preview'));
}
function insertText(before, after = '', placeholder = '') {
  const area = $('body'), start = area.selectionStart, end = area.selectionEnd;
  const chosen = area.value.slice(start, end) || placeholder;
  area.setRangeText(before + chosen + after, start, end, 'select');
  state.draft.document.body = area.value; dirty(); area.focus();
}
const base64 = file => new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(new Error('Could not read the file.')); reader.readAsDataURL(file); });
async function prepareImage(file) {
  if (!['image/png','image/jpeg','image/gif','image/webp'].includes(file.type)) throw new Error('Choose a PNG, JPEG, GIF, or WebP image.');
  if (file.size <= 1024 * 1024) return base64(file);
  if (file.size > 15 * 1024 * 1024 || file.type === 'image/gif') throw new Error('Choose a smaller image. Animated GIFs must be under 1 MB.');
  const image = new Image(); image.src = `data:${file.type};base64,${await base64(file)}`; await image.decode();
  const scale = Math.min(1, 1600 / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement('canvas'); canvas.width = Math.max(1, Math.round(image.naturalWidth * scale)); canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
  const context = canvas.getContext('2d'); context.fillStyle = '#ffffff'; context.fillRect(0, 0, canvas.width, canvas.height); context.drawImage(image, 0, 0, canvas.width, canvas.height);
  const reduced = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .82));
  if (!reduced || reduced.size > 1024 * 1024) throw new Error('This image is still too large. Resize it before uploading.');
  return base64(reduced);
}
async function upload(file, field) {
  const encoded = await prepareImage(file); await save();
  const result = await api('upload', { id: state.draft.id, revision: state.revision, base64: encoded, ...(field ? { field } : {}) });
  state.images.set(result.asset.id, Promise.resolve(`data:${result.asset.mime};base64,${encoded}`));
  if (mergeWritingResult(state, result)) renderFields();
  if (field) {
    notice('Cover image saved privately. Add its description and optional caption below, then review and publish when ready.');
    return;
  }
  insertText(`\n\n![Describe the image](${result.asset.publicPath})\n\n`);
  await save(); notice('Image saved privately. Replace “Describe the image” with a useful description.');
}
async function review() {
  await save(); state.review = await api('review', { id: state.draft.id, revision: state.revision });
  $('review-description').textContent = state.review.visible ? 'Review the content and exact changes below. Nothing goes public until you choose Publish.' : 'This update keeps the entry hidden on the website. Its source will still be in the public repository.';
  $('review-diff').replaceChildren(renderDiff(state.review.before, state.review.after));
  $('review-paths').replaceChildren(...state.review.paths.map(path => element('li', path)));
  preview(state.draft.document, $('review-content')); $('review-dialog').showModal();
}
async function publish() {
  if (!state.review) throw new Error('Review this draft before publishing.');
  const result = await api('publish', { id: state.draft.id, receipt: state.review.receipt });
  $('review-dialog').close(); state.review = null;
  if (result.saved) showDraft(result.saved);
  notice(result.warning || 'Your update was committed. GitHub Pages is building the website; it may take a few minutes.', Boolean(result.warning), result.commitUrl);
  await refreshLists();
}

const writingChat = createWritingChat({ api, stream: (route, data, onEvent, signal) => liveRequest(route, data, state.auth?.csrf || '', onEvent, signal),
  current: () => state, save, available: () => Boolean(state.auth?.ai), locked: () => state.busy, notice,
  receive(result) {
    if (mergeWritingResult(state, result)) { renderFields(); setView('write'); }
    updateSaveState();
  }
});

const siteChat = createSiteChat({ api, apiStream: (route, data, onEvent, signal) => liveRequest(route, data, state.auth?.csrf || '', onEvent, signal), run, notice, leaveDraft, aiAvailable: () => Boolean(state.auth?.ai), onPublished: refreshLists, onWorkingFiles: changes => { state.pendingFiles = changes; renderList(); } });
$('body').addEventListener('input', () => { state.draft.document.body = $('body').value; dirty(); });
$('save').addEventListener('click', () => run(save, 'Saving privately…'));
$('review').addEventListener('click', () => run(review, 'Preparing review…'));
$('publish').addEventListener('click', () => run(publish, 'Publishing approved changes…'));
$('write-tab').addEventListener('click', () => setView('write'));
$('preview-tab').addEventListener('click', () => setView('preview'));
$('filter').addEventListener('input', renderList);
for (const tab of ['drafts','content','files']) $(tab + '-tab').addEventListener('click', () => { state.list = tab; $('filter').value = ''; for (const name of ['drafts','content','files']) $(name + '-tab').setAttribute('aria-pressed', String(tab === name)); renderList(); });
function newDestination() { $('new-destination').textContent = 'Website destination: ' + contentPath($('new-kind').value, $('new-slug').value || 'your-title', $('new-date').value || 'YYYY-MM-DD'); }
function newDialog() { $('new-date').value = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()); $('new-title').value = ''; $('new-slug').value = ''; newDestination(); $('new-dialog').showModal(); }
$('new').addEventListener('click', newDialog);
$('create-post').addEventListener('click', newDialog);
for (const id of ['new-kind', 'new-date', 'new-slug']) $(id).addEventListener('input', newDestination);
$('new-title').addEventListener('input', () => { $('new-slug').value = $('new-title').value.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/['’]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 100); newDestination(); });
$('new-form').addEventListener('submit', event => { event.preventDefault(); run(async () => {
  if (!siteChat.leaveFile() || !(await leaveDraft())) return;
  const result = await api('open', { kind: $('new-kind').value, slug: $('new-slug').value, date: $('new-date').value });
  result.draft.document.fields.title = $('new-title').value;
  showDraft(result); dirty(); await save(); $('new-dialog').close(); await refreshLists();
}, 'Creating private draft…'); });
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => $(button.dataset.close).close()));
$('restore').addEventListener('click', () => run(async () => {
  if (!confirm('Load the previous published version into this private draft? Your website will not change until you review and publish.')) return;
  await save(); showDraft(await api('restore', { id: state.draft.id, revision: state.revision })); notice('Previous version loaded into your private draft. Review it before publishing.');
}, 'Loading previous version…'));
$('image-button').addEventListener('click', () => $('image-file').click());
$('image-file').addEventListener('change', event => { const file = event.target.files[0]; if (file) run(() => upload(file), 'Saving image privately…'); event.target.value = ''; });
$('body').addEventListener('paste', event => { const item = [...(event.clipboardData?.items || [])].find(item => item.kind === 'file' && item.type.startsWith('image/')); if (item) { event.preventDefault(); const file = item.getAsFile(); if (file) run(() => upload(file), 'Saving pasted image…'); } });
$('format-bar').addEventListener('click', event => {
  const type = event.target.closest('[data-format]')?.dataset.format;
  if (type === 'math') insertText('$$', '$$', 'x_i^2');
  if (type === 'display-math') insertText('\n\n$$\n', '\n$$\n\n', '\\hat{\\theta} = \\frac{1}{n} \\sum_{i=1}^{n} x_i');
  if (type === 'bold') insertText('**', '**', 'bold text');
  if (type === 'italic') insertText('*', '*', 'italic text');
  if (type === 'heading') insertText('\n\n## ', '\n', 'Heading');
  if (type === 'list') insertText('\n- ', '\n', 'List item');
  if (type === 'quote') insertText('\n> ', '\n', 'Quotation');
  if (type === 'link') {
    const url = prompt('Link address', 'https://');
    if (!url) return;
    if (!linkTarget(url.trim())) return notice('Use an https://, http://, mailto:, or website /path link.', true);
    insertText('[', `](${url.trim().replaceAll(')', '%29')})`, 'link text');
  }
});
$('logout').addEventListener('click', () => run(async () => { if (!(await leaveDraft())) return; await api('logout', {}); location.assign('/'); }));
window.addEventListener('beforeunload', event => { if (state.dirty || writingChat.isBusy()) { event.preventDefault(); event.returnValue = ''; } });
document.addEventListener('keydown', event => { if ((event.metaKey || event.ctrlKey) && event.key === 's' && state.draft) { event.preventDefault(); run(save, 'Saving privately…'); } });
let initializing = false;
async function initialize() {
  if (initializing) return;
  initializing = true;
  $('startup-status').textContent = 'Opening your editor…'; $('startup-retry').hidden = true;
  if (new URL(location.href).searchParams.get('error') === 'account') notice('This editor is restricted to Nate’s GitHub account.', true);
  try {
    state.auth = await api('session');
    $('ask').disabled = !state.auth.ai;
    // Prepare the intended view while the app is hidden. Settle both reads
    // before offering a retry so an older initialization cannot change it.
    const results = await Promise.allSettled([siteChat.activate(), refreshLists()]);
    const failed = results.find(result => result.status === 'rejected');
    if (failed) throw failed.reason;
    $('startup').hidden = true; $('app').hidden = false; $('logout').hidden = false;
    if (!state.auth.ai) notice('The editor is connected. Add an OpenAI key in hosting settings to enable GPT; manual editing is available.');
  } catch (error) {
    if (error.status === 401) { state.auth = null; $('startup').hidden = true; $('login').hidden = false; }
    else { $('startup-status').textContent = error.message; $('startup-retry').hidden = false; }
  } finally { initializing = false; }
}
$('startup-retry').addEventListener('click', initialize);
initialize();
