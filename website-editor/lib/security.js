import { createCipheriv, createDecipheriv, createHash, randomBytes, timingSafeEqual } from 'node:crypto';

export class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
export const SITE = 'NateOConnellPhD/nateoconnell.github.io';
export const SITE_URL = 'https://nateoconnell.com';
export const SESSION = '__Host-site-editor';
export const STATE = '__Host-editor-oauth';
export const nonce = () => randomBytes(32).toString('base64url');
export const digest = (text) => createHash('sha256').update(text).digest('hex');
export const blobSha = (text) => createHash('sha1').update(`blob ${Buffer.byteLength(text)}\0`).update(text).digest('hex');
export function equal(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  const left = Buffer.from(a), right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}
export function configuration(env = process.env) {
  const required = ['APP_ORIGIN', 'GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET', 'ALLOWED_GITHUB_USER_ID', 'SESSION_SECRET', 'DRAFT_REPOSITORY'];
  if (required.some(key => !env[key])) throw new HttpError(503, 'The editor needs its hosting configuration. See the setup guide.');
  const origin = new URL(env.APP_ORIGIN);
  if (origin.protocol !== 'https:' || origin.origin !== env.APP_ORIGIN || !/^\d+$/.test(env.ALLOWED_GITHUB_USER_ID) || !/^[a-f0-9]{64}$/i.test(env.SESSION_SECRET)) {
    throw new HttpError(503, 'Editor origin, account ID, or session secret is not configured correctly.');
  }
  if (!/^NateOConnellPhD\/[A-Za-z0-9_.-]+$/.test(env.DRAFT_REPOSITORY) || env.DRAFT_REPOSITORY.toLowerCase() === SITE.toLowerCase()) {
    throw new HttpError(503, 'Choose a separate private repository for drafts.');
  }
  const daily = Number(env.MAX_DAILY_AI_REQUESTS || 40);
  if (!Number.isInteger(daily) || daily < 1 || daily > 100) throw new HttpError(503, 'Daily AI request limit must be between 1 and 100.');
  return { origin: origin.origin, clientId: env.GITHUB_CLIENT_ID, clientSecret: env.GITHUB_CLIENT_SECRET,
    ownerId: env.ALLOWED_GITHUB_USER_ID, secret: env.SESSION_SECRET, drafts: env.DRAFT_REPOSITORY,
    apiKey: env.OPENAI_API_KEY || '', model: env.OPENAI_MODEL || 'gpt-5.4-mini', agentModel: env.OPENAI_AGENT_MODEL || 'gpt-6-astra', daily };
}
export function seal(payload, purpose, config, ttl = 3600) {
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', Buffer.from(config.secret, 'hex'), iv);
  cipher.setAAD(Buffer.from(purpose));
  const encrypted = Buffer.concat([cipher.update(JSON.stringify({ ...payload, exp: Math.floor(Date.now() / 1000) + ttl }), 'utf8'), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), encrypted]).toString('base64url');
}
export function unseal(value, purpose, config) {
  try {
    if (typeof value !== 'string' || value.length > 8000) return null;
    const bytes = Buffer.from(value, 'base64url');
    const decipher = createDecipheriv('aes-256-gcm', Buffer.from(config.secret, 'hex'), bytes.subarray(0, 12));
    decipher.setAAD(Buffer.from(purpose)); decipher.setAuthTag(bytes.subarray(12, 28));
    const data = JSON.parse(Buffer.concat([decipher.update(bytes.subarray(28)), decipher.final()]).toString());
    return Number.isFinite(data.exp) && data.exp > Date.now() / 1000 ? data : null;
  } catch { return null; }
}
export function cookie(name, value, age = 28800) {
  return `${name}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${age}`;
}
export function cookies(request) {
  return Object.fromEntries((request.headers.get('cookie') || '').split(';').map(p => p.trim().split(/=(.*)/s).slice(0, 2)).filter(p => p.length === 2));
}
export function session(request, config) {
  const value = unseal(cookies(request)[SESSION], 'session', config);
  if (!value || String(value.id) !== config.ownerId || !value.token || !value.csrf) throw new HttpError(401, 'Please sign in again. Your saved drafts are still private.');
  return value;
}
export function requireMutation(request, current, config) {
  if (request.method !== 'POST') throw new HttpError(405, 'Use POST for changes.');
  if (request.headers.get('origin') !== config.origin || !equal(request.headers.get('x-csrf-token'), current.csrf)) {
    throw new HttpError(403, 'The request could not be verified. Reload the editor and try again.');
  }
}
export async function readJson(request) {
  if (!request.headers.get('content-type')?.startsWith('application/json')) throw new HttpError(415, 'Expected JSON.');
  const max = 3 * 1024 * 1024;
  if (Number(request.headers.get('content-length')) > max) throw new HttpError(413, 'This upload is too large.');
  const reader = request.body?.getReader(); let size = 0; const chunks = [];
  if (!reader) throw new HttpError(400, 'Missing request.');
  for (;;) {
    const { value, done } = await reader.read(); if (done) break;
    size += value.byteLength;
    if (size > max) { await reader.cancel(); throw new HttpError(413, 'This upload is too large.'); }
    chunks.push(Buffer.from(value));
  }
  try { return JSON.parse(Buffer.concat(chunks).toString()); } catch { throw new HttpError(400, 'Invalid JSON.'); }
}
export function validId(value) {
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value || '')) throw new HttpError(400, 'Invalid draft ID.');
  return value;
}
