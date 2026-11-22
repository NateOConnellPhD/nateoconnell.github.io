import { blogRows, libraryTitle } from './library.js';

const $ = id => document.getElementById(id);
const node = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
};
const savedDate = value => new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });

export function createBlogPosts({ open, create, retry }) {
  let filter = 'all', data = { files: [], drafts: [], pending: [] };
  function render(next = data) {
    data = next;
    const container = $('blog-post-list'); container.replaceChildren();
    $('blog-post-status').textContent = data.error || (data.loading ? 'Loading blog posts…' : '');
    $('blog-post-retry').hidden = !data.error;
    container.setAttribute('aria-busy', String(Boolean(data.loading)));
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    const rows = blogRows(data.files, data.drafts, today);
    const matchesFilter = (row, chosen) => chosen === 'all' || (chosen === 'published' ? row.status === 'Published' : row.drafts.length > 0);
    for (const button of document.querySelectorAll('[data-blog-filter]')) {
      const chosen = button.dataset.blogFilter;
      button.setAttribute('aria-pressed', String(chosen === filter));
      button.textContent = `${{ all: 'All posts', published: 'Published', drafts: 'Saved drafts' }[chosen]}${data.loading || data.error ? '' : ` (${rows.filter(row => !row.file?.example && matchesFilter(row, chosen)).length})`}`;
    }
    if (data.loading || data.error) return;
    const query = $('blog-post-search').value.trim().toLocaleLowerCase();
    const examples = node('details', undefined, 'blog-examples');
    let count = 0, exampleCount = 0;
    for (const row of rows) {
      if (!matchesFilter(row, filter) || !`${row.title} ${row.file ? libraryTitle(row.file) : ''} ${row.drafts.map(d => d.title).join(' ')} ${row.path}`.toLocaleLowerCase().includes(query)) continue;
      const pending = data.pending.some(change => change.path === row.path);
      const entry = node('article', undefined, 'blog-post-row');
      const info = node('div', undefined, 'blog-post-info'), heading = node('h2');
      const title = node('button', row.title, 'blog-post-title'); title.type = 'button';
      const edit = () => open(row, pending || row.file?.metadataError ? 'source' : row.drafts.length ? 'draft' : 'website');
      title.addEventListener('click', edit); heading.append(title); info.append(heading);
      const meta = node('div', undefined, 'blog-post-meta');
      const badge = node('span', row.status, 'post-status'); badge.dataset.status = row.status;
      meta.append(badge);
      if (row.file) meta.append(node('span', row.date));
      if (row.drafts.length) meta.append(node('span', `Draft saved ${savedDate(row.drafts[0].updated)}`));
      if (pending) meta.append(node('span', 'Chat changes pending'));
      info.append(meta);
      const actions = node('div', undefined, 'blog-post-actions');
      const action = node('button', pending || row.file?.metadataError ? 'Edit source' : row.drafts.length ? 'Continue draft' : 'Edit post', 'button');
      action.type = 'button'; action.setAttribute('aria-label', `${action.textContent}: ${row.title}`); action.addEventListener('click', edit); actions.append(action);
      entry.append(info, actions);
      if (row.drafts.length > 1 || row.file && row.drafts.length && !row.file.metadataError && !pending) {
        const versions = node('details', undefined, 'blog-post-versions');
        versions.append(node('summary', 'Other versions'));
        if (row.file && !row.file.metadataError && !pending) {
          const fresh = node('button', 'Start a new draft from the website version', 'quiet'); fresh.type = 'button';
          fresh.addEventListener('click', () => open(row, 'website')); versions.append(fresh);
        }
        for (const draft of row.drafts.slice(1)) {
          const old = node('button', `${draft.title} · Saved ${savedDate(draft.updated)}`, 'quiet'); old.type = 'button';
          old.addEventListener('click', () => open(row, 'draft', draft.id)); versions.append(old);
        }
        entry.append(versions);
      }
      if (row.file?.example) { examples.append(entry); exampleCount++; }
      else { container.append(entry); count++; }
    }
    if (!count) container.append(node('p', query ? 'No posts match your search.' : filter === 'drafts' ? 'No saved blog drafts yet.' : filter === 'published' ? 'No published posts yet.' : 'No blog posts yet. Start with New post.', 'blog-post-empty'));
    if (exampleCount) { examples.prepend(node('summary', `Example posts (${exampleCount})`)); examples.open = Boolean(query); container.append(examples); }
  }
  $('blog-post-search').addEventListener('input', () => render());
  for (const button of document.querySelectorAll('[data-blog-filter]')) button.addEventListener('click', () => { filter = button.dataset.blogFilter; render(); });
  $('blog-post-new').addEventListener('click', create);
  $('blog-post-retry').addEventListener('click', retry);
  return { render };
}
