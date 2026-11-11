import { HttpError } from './security.js';
import { schemas, kindForPath, contentPath } from '../public/schema.js';

const sizeLimit = 100000;
export function safeText(value) {
  if (typeof value !== 'string' || Buffer.byteLength(value) > sizeLimit || value.includes('\0')) throw new HttpError(400, 'Text is missing or too long.');
  const links = value.replace(/&#x([a-f\d]+);?|&#(\d+);?|&(colon|tab|newline);/gi, (_, hex, decimal, named) => {
    if (named) return { colon: ':', tab: '\t', newline: '\n' }[named.toLowerCase()];
    const point = parseInt(hex || decimal, hex ? 16 : 10);
    return point >= 0 && point <= 0x10ffff ? String.fromCodePoint(point) : '';
  }).replace(/[\u0000-\u0020]/g, '');
  if (/{[{%]/.test(value) || /<\/?[a-z][^>]*>/i.test(value) || /(?:\]\(<?|\[[^\]]+\]:<?)(?:javascript|vbscript|data):/i.test(links)) {
    throw new HttpError(400, 'Use Markdown rather than HTML, scripts, or Liquid template code.');
  }
  return value;
}
function safeUrl(value) {
  if (value === '') return value;
  if (/^\/(?!\/)[^\s\\]*$/.test(value)) return value;
  try { if (['https:', 'http:', 'mailto:'].includes(new URL(value).protocol)) return value; } catch { /* reject */ }
  throw new HttpError(400, 'Links must use https://, http://, mailto:, or a site path beginning with /.');
}
function checkField(value, spec, publish) {
  if (value === undefined || value === null) value = spec.type === 'boolean' ? false : spec.type === 'tags' || spec.type === 'list' ? [] : spec.type === 'number' ? 0 : '';
  if (spec.type === 'boolean') { if (typeof value !== 'boolean') throw new HttpError(400, `Invalid ${spec.label}.`); return value; }
  if (spec.type === 'number') { if (!Number.isFinite(value) || Math.abs(value) > 100000) throw new HttpError(400, `Invalid ${spec.label}.`); return value; }
  if (spec.type === 'tags') {
    if (!Array.isArray(value) || value.length > 30) throw new HttpError(400, 'Too many topics.');
    return value.map(v => safeText(v).trim()).filter(Boolean);
  }
  if (spec.type === 'list') {
    if (!Array.isArray(value) || value.length > 30) throw new HttpError(400, `Invalid ${spec.label}.`);
    return value.map(item => {
      if (!item || typeof item !== 'object' || Array.isArray(item) || Object.keys(item).some(key => !Object.hasOwn(spec.fields, key))) throw new HttpError(400, 'Invalid list entry.');
      return Object.fromEntries(Object.entries(item).map(([key, entry]) => [key, checkField(entry, spec.fields[key], publish)]));
    });
  }
  const result = safeText(value);
  if (publish && spec.required && !result.trim()) throw new HttpError(400, `${spec.label} is required before publishing.`);
  if (spec.type === 'date' && result && (!/^\d{4}-\d{2}-\d{2}$/.test(result) || !Number.isFinite(Date.parse(result)) || new Date(result).toISOString().slice(0, 10) !== result)) throw new HttpError(400, `Invalid ${spec.label}.`);
  if (spec.type === 'select' && !spec.options.includes(result)) throw new HttpError(400, `Choose a valid ${spec.label.toLowerCase()}.`);
  return spec.url ? safeUrl(result) : result;
}
export function validateDocument(document, publish = false) {
  if (!document || kindForPath(document.path) !== document.kind || !Object.hasOwn(schemas, document.kind)) throw new HttpError(403, 'This file is outside the editor’s content scope.');
  const schema = schemas[document.kind];
  if (!document.fields || typeof document.fields !== 'object' || Array.isArray(document.fields) || Object.keys(document.fields).some(key => !Object.hasOwn(schema.fields, key))) throw new HttpError(400, 'Unknown content field.');
  const fields = Object.fromEntries(Object.entries(document.fields).map(([key, entry]) => [key, checkField(entry, schema.fields[key], publish)]));
  if (publish) for (const [key, spec] of Object.entries(schema.fields)) if (spec.required && !Object.hasOwn(fields, key)) checkField(undefined, spec, true);
  if (publish && document.kind === 'post') {
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    if (fields.date > today) throw new HttpError(400, 'Future-dated posts need a later site build. Keep this as a private draft until its publication date.');
    if (!document.path.startsWith(`_posts/${fields.date}-`)) throw new HttpError(400, 'The publication date must match this post’s filename. Create a new post to use a different date.');
  }
  const body = schema.body ? safeText(document.body || '') : '';
  if (Buffer.byteLength(JSON.stringify({ fields, body })) > sizeLimit) throw new HttpError(413, 'This document exceeds the editor’s 100 KB limit.');
  return { path: document.path, kind: document.kind, fields, body };
}
async function yamlDocument(source) {
  const { parseDocument } = await import('yaml');
  const document = parseDocument(source, { schema: 'core', uniqueKeys: true, customTags: [] });
  if (document.errors.length || document.warnings.length) throw new HttpError(400, 'This document has unsupported or invalid YAML.');
  const value = document.toJS({ maxAliasCount: 0 });
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new HttpError(400, 'Expected a YAML mapping.');
  return { document, value };
}
function split(source, kind) {
  if (!schemas[kind].body) return { yaml: source, body: '' };
  const match = source.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!match) throw new HttpError(400, 'Expected Markdown with YAML front matter.');
  return { yaml: match[1], body: match[2].replace(/^\n/, '') };
}
export async function parseSource(path, source) {
  const kind = kindForPath(path);
  if (!kind || Buffer.byteLength(source) > sizeLimit) throw new HttpError(400, 'Unsupported content file.');
  const parts = split(source, kind);
  const { value } = await yamlDocument(parts.yaml);
  const fields = Object.fromEntries(Object.entries(value).filter(([key]) => Object.hasOwn(schemas[kind].fields, key)));
  return validateDocument({ path, kind, fields, body: parts.body });
}
export async function serialize(document, original = '', publish = false) {
  const checked = validateDocument(document, publish);
  const schema = schemas[checked.kind];
  const originalYaml = original ? split(original, checked.kind).yaml : 'example: false\n';
  const { document: yaml, value } = await yamlDocument(originalYaml);
  for (const [key, entry] of Object.entries(checked.fields)) {
    if (JSON.stringify(value[key]) !== JSON.stringify(entry)) yaml.set(key, entry);
  }
  const result = yaml.toString({ lineWidth: 0 });
  return schema.body ? `---\n${result}---\n${checked.body.trimEnd()}\n` : result;
}
export function newPath(kind, slug, date) {
  const schema = schemas[kind];
  if (!schema?.folder || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug || '') || slug.length > 100 || !/^\d{4}-\d{2}-\d{2}$/.test(date || '')) throw new HttpError(400, 'Choose a title slug and a valid date.');
  return contentPath(kind, slug, date);
}
export function imageUpload(data) {
  if (!data || typeof data.base64 !== 'string' || !/^[A-Za-z0-9+/]*={0,2}$/.test(data.base64)) throw new HttpError(400, 'Invalid image upload.');
  const buffer = Buffer.from(data.base64, 'base64');
  if (buffer.length < 12 || buffer.length > 1024 * 1024) throw new HttpError(413, 'Use an image smaller than 1 MB.');
  let ext, mime;
  if (buffer.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) { ext = 'png'; mime = 'image/png'; }
  else if (buffer[0] === 255 && buffer[1] === 216 && buffer[2] === 255) { ext = 'jpg'; mime = 'image/jpeg'; }
  else if (/^GIF8[79]a$/.test(buffer.subarray(0, 6).toString())) { ext = 'gif'; mime = 'image/gif'; }
  else if (buffer.subarray(0, 4).toString() === 'RIFF' && buffer.subarray(8, 12).toString() === 'WEBP') { ext = 'webp'; mime = 'image/webp'; }
  else throw new HttpError(400, 'Choose a PNG, JPEG, GIF, or WebP image.');
  return { buffer, ext, mime };
}
