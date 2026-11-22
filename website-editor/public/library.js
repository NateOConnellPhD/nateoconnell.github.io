import { schemas, kindForPath } from './schema.js';

export const librarySections = {
  pages: { label: 'Pages', kinds: ['home', 'profile', 'about', 'cv', 'introductions'] },
  posts: { label: 'Blog posts', kinds: ['post'], create: 'post', action: 'New post' },
  research: { label: 'Research', kinds: ['research'], create: 'research', action: 'Add research' },
  talks: { label: 'Talks', kinds: ['talk'], create: 'talk', action: 'Add talk' }
};

export function libraryTitle(item) {
  const kind = item.kind || kindForPath(item.path);
  if (schemas[kind]?.path) return kind === 'cv' ? 'CV' : schemas[kind].label;
  return item.title || item.path.split('/').pop().replace(/\.md$/, '').replace(/^\d{4}-\d{2}-\d{2}-/, '').replaceAll('-', ' ');
}

export function sectionItems(files, section) {
  const { kinds } = librarySections[section];
  return files.filter(item => kinds.includes(item.kind)).sort((a, b) => {
    if (section === 'pages') return kinds.indexOf(a.kind) - kinds.indexOf(b.kind);
    if (section === 'posts' || section === 'talks') return String(b.date || b.path).localeCompare(String(a.date || a.path));
    return libraryTitle(a).localeCompare(libraryTitle(b));
  });
}

// Keep one post per destination while retaining every saved version. Draft
// indexes from older editor releases have a path, but no explicit kind.
export function blogRows(files, drafts, today) {
  const rows = new Map();
  for (const file of files.filter(item => kindForPath(item.path) === 'post')) {
    rows.set(file.path, { path: file.path, file, drafts: [] });
  }
  for (const draft of drafts.filter(item => kindForPath(item.path) === 'post')) {
    if (!rows.has(draft.path)) rows.set(draft.path, { path: draft.path, file: null, drafts: [] });
    rows.get(draft.path).drafts.push(draft);
  }
  return [...rows.values()].map(row => {
    row.drafts.sort((a, b) => String(b.updated).localeCompare(String(a.updated)) || a.id.localeCompare(b.id));
    row.title = row.drafts[0]?.title || libraryTitle(row.file || row);
    row.date = (row.file?.date || row.path.match(/^_posts\/(\d{4}-\d{2}-\d{2})-/)?.[1] || '').slice(0, 10);
    row.status = !row.file ? 'Private draft' : row.file.metadataError ? 'Source file'
      : row.file.published === false || row.file.example ? 'Hidden' : row.date > today ? 'Future dated' : 'Published';
    return row;
  }).sort((a, b) => String(b.drafts[0]?.updated || b.date).localeCompare(String(a.drafts[0]?.updated || a.date)) || a.title.localeCompare(b.title));
}
