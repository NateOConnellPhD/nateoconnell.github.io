const text = (label, extra = {}) => ({ label, type: 'text', ...extra });
const long = (label, extra = {}) => ({ label, type: 'long', ...extra });
const common = { title: text('Title', { required: true }), description: long('Short description') };
const visible = { published: { label: 'Visible on the website after publishing', type: 'boolean' } };
export const schemas = {
  post: { label: 'Blog post', folder: '_posts', body: true, fields: {
    ...common, description: long('Short description', { required: true, help: 'Appears below the title on the homepage and blog page. Required before publishing.' }),
    date: { label: 'Publication date', type: 'date', required: true }, tags: { label: 'Topics', type: 'tags' },
    cover: { label: 'Cover image', type: 'image', url: true }, cover_alt: text('Cover image description'), cover_caption: text('Cover caption'), ...visible,
    comments: { label: 'Show discussion', type: 'boolean', default: true, help: 'Show the GitHub comments and replies below this post once site-wide comments are connected.' }
  } },
  research: { label: 'Research entry', folder: '_research', body: true, fields: {
    title: common.title, kind: { label: 'Type', type: 'select', options: ['Publication', 'Preprint', 'Manuscript', 'Project', 'Other'] },
    area: { label: 'Research area', type: 'select', options: ['Methods & theory', 'Clinical research'] },
    study: text('Study label'), year: { label: 'Year', type: 'number' }, authors: text('Authors'), venue: text('Journal or status'),
    summary: long('Summary'), link: text('Paper or project link', { url: true }), pdf: text('PDF link', { url: true }), code: text('Code link', { url: true }),
    order: { label: 'Display order', type: 'number' }, featured: { label: 'Feature on the homepage', type: 'boolean' }, ...visible
  } },
  talk: { label: 'Talk', folder: '_talks', body: true, fields: {
    title: common.title, kind: { label: 'Format', type: 'select', options: ['Talk', 'Seminar', 'Grand rounds', 'Workshop', 'Panel', 'Lecture'] },
    event_date: { label: 'Event date', type: 'date', required: true }, venue: text('Event or host'), summary: long('Description'),
    slides: text('Slides link', { url: true }), recording: text('Recording link', { url: true }), event_url: text('Event link', { url: true }), ...visible
  } },
  about: { label: 'About me', path: '_pages/about.md', body: true, fields: common },
  cv: { label: 'CV text', path: '_pages/cv.md', body: true, fields: { ...common, pdf: text('CV PDF link', { url: true }), updated: { label: 'Updated', type: 'date' } } },
  home: { label: 'Homepage & contact', path: '_data/home.yml', fields: {
    eyebrow: text('Small heading'), heading: text('Name heading'), research_intro: long('Research introduction'),
    blog_intro: long('Blog introduction'), contact_heading: text('Contact heading'), contact_text: long('Contact & mentorship', { markdown: true })
  } },
  profile: { label: 'Profile & links', path: '_data/profile.yml', fields: {
    name: text('Name'), role: text('Title'), department: text('Department'), division: text('Division'), affiliation: text('Institution'),
    introduction: long('Opening introduction'), email: text('Email'), portrait: text('Headshot path', { url: true }), portrait_alt: text('Headshot description'),
    interests: { label: 'Research interests', type: 'list', fields: { name: text('Topic'), description: long('Description') } },
    links: { label: 'Profile links', type: 'list', fields: { label: text('Label'), url: text('URL', { url: true }), personal: { label: 'Personal profile', type: 'boolean', default: true } } }
  } },
  introductions: { label: 'Research introductions', path: '_data/research.yml', fields: {
    introduction: long('Methods & theory', { markdown: true }), clinical_introduction: long('Clinical research', { markdown: true })
  } }
};
export function kindForPath(path) {
  if (typeof path !== 'string') return null;
  for (const [kind, schema] of Object.entries(schemas)) {
    if (schema.path === path) return kind;
    if (schema.folder && new RegExp(`^${schema.folder}/[a-z0-9][a-z0-9-]*\\.md$`).test(path)) return kind;
  }
  return null;
}
export function contentPath(kind, slug, date) {
  return `${schemas[kind].folder}/${kind === 'research' ? '' : date + '-'}${slug}.md`;
}
export const initialFields = (kind, date) => ({
  ...(schemas[kind]?.fields.published ? { published: true } : {}),
  ...(kind === 'post' ? { date, tags: [], comments: true } : {}),
  ...(kind === 'talk' ? { event_date: date, kind: 'Talk' } : {}),
  ...(kind === 'research' ? { kind: 'Manuscript', area: 'Methods & theory', year: Number(date.slice(0, 4)), order: 10, featured: false } : {})
});
