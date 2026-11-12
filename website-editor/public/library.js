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
