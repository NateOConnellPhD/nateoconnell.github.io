import { createHash } from 'node:crypto';
import { HttpError, readJson, SITE_URL } from './security.js';

const DAY = 86400000;
const TTL = 5 * 60000;
const PAGE_LIMIT = 1000;
const ENDPOINT = 'https://api.cloudflare.com/client/v4/graphql';
const QUERY = `query WebsiteTraffic($account: string!, $filter: AccountRumPageloadEventsAdaptiveGroupsFilter_InputObject!) {
  viewer { accounts(filter: { accountTag: $account }) {
    totals: rumPageloadEventsAdaptiveGroups(limit: 10, filter: $filter) {
      count dimensions { bot } avg { sampleInterval }
    }
    daily: rumPageloadEventsAdaptiveGroups(limit: 200, filter: $filter, orderBy: [date_ASC]) {
      count dimensions { date bot } avg { sampleInterval }
    }
    pages: rumPageloadEventsAdaptiveGroups(limit: 1000, filter: $filter, orderBy: [count_DESC]) {
      count dimensions { requestPath bot } avg { sampleInterval }
    }
  } }
}`;

export function pagePath(value) {
  if (typeof value !== 'string' || value.length > 1024 || !/^\/(?!\/)[^\s?#\\<>]*$/.test(value)) return null;
  try {
    const encoded = value.replace(/[^\x00-\x7F]/gu, character => encodeURIComponent(character));
    return new URL(value, SITE_URL).pathname === encoded ? value : null;
  } catch { return null; }
}

export function trafficOptions(params, now) {
  const days = Number(params.get('days') || 7), scope = params.get('scope') || 'site', path = params.get('path') || '';
  if (![1, 7, 28].includes(days) || !['site', 'blog'].includes(scope)) throw new HttpError(400, 'Choose today, 7 days, or 28 days, and either the site or blog posts.');
  if (path && (!pagePath(path) || scope === 'blog' && (!path.startsWith('/blog/') || path === '/blog/'))) throw new HttpError(400, 'Choose a valid page path.');
  const end = new Date(now), midnight = Date.parse(end.toISOString().slice(0, 10) + 'T00:00:00Z');
  return { days, scope, path, start: new Date(midnight - (days - 1) * DAY).toISOString(), end: end.toISOString(), timezone: 'UTC' };
}

function connection(env) {
  const names = ['CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_WEB_ANALYTICS_SITE_TAG', 'CLOUDFLARE_ANALYTICS_TOKEN'];
  const missing = names.filter(name => !env[name]?.trim());
  if (missing.length) return { missing };
  const [account, site, token] = names.map(name => env[name].trim());
  if (![account, site].every(value => /^[a-f0-9]{32}$/i.test(value)) || token.length > 2048 || /[\s\r\n]/.test(token)) throw new HttpError(503, 'The Cloudflare analytics configuration is invalid. Check the account ID, site tag, and read-only API token.');
  return { account, site, token };
}

const blank = () => ({ all: 0, notFlagged: 0, bots: 0, unclassified: 0 });
function add(counts, row) {
  if (!row || !Number.isFinite(row.count) || row.count < 0 || row.count > Number.MAX_SAFE_INTEGER || !row.dimensions) throw new Error('Invalid analytics row');
  const count = Math.round(row.count), bot = row.dimensions.bot;
  counts.all += count;
  if (bot === 1 || bot === '1' || bot === true) counts.bots += count;
  else if (bot === 0 || bot === '0' || bot === false) counts.notFlagged += count;
  else counts.unclassified += count;
}

export function summarizeTraffic(account, range) {
  if (!account || !['totals', 'daily', 'pages'].every(name => Array.isArray(account[name]))) throw new Error('Missing analytics groups');
  const totals = blank(), days = new Map(), pages = new Map();
  for (let day = Date.parse(range.start); day < Date.parse(range.end); day += DAY) days.set(new Date(day).toISOString().slice(0, 10), blank());
  // At exactly midnight the current day is still a useful zero-width bin.
  const today = range.end.slice(0, 10);
  if (!days.has(today)) days.set(today, blank());
  for (const row of account.totals) add(totals, row);
  for (const row of account.daily) {
    const counts = days.get(row.dimensions?.date);
    if (!counts) throw new Error('Unexpected analytics date');
    add(counts, row);
  }
  for (const row of account.pages) {
    const path = pagePath(row.dimensions?.requestPath);
    if (!path) throw new Error('Unexpected analytics path');
    if (!pages.has(path)) pages.set(path, { path, ...blank() });
    add(pages.get(path), row);
  }
  return { totals, daily: [...days].map(([date, counts]) => ({ date, ...counts })),
    pages: [...pages.values()].sort((a, b) => b.all - a.all || a.path.localeCompare(b.path)),
    pagesLimited: account.pages.length >= PAGE_LIMIT,
    sampled: [...account.totals, ...account.daily, ...account.pages].some(row => Number(row.avg?.sampleInterval) > 1) };
}

export function createTrafficService({ fetchImpl = fetch, now = Date.now } = {}) {
  const cache = new Map(), pending = new Map();
  let catalog = null, catalogUntil = 0, catalogPending = null;
  async function postCatalog() {
    if (now() < catalogUntil) return catalog || {};
    if (catalogPending) return catalogPending;
    catalogPending = (async () => {
      try {
        const response = await fetchImpl(`${SITE_URL}/traffic-posts.json`, { signal: AbortSignal.timeout(8000), redirect: 'error' });
        if (!response.ok) throw new Error('Catalog unavailable');
        const data = await readJson(response);
        if (!Array.isArray(data.posts) || data.posts.length > 5000) throw new Error('Invalid catalog');
        catalog = Object.fromEntries(data.posts.filter(post => pagePath(post.path) && post.path.startsWith('/blog/') && post.path !== '/blog/' && typeof post.title === 'string' && post.title.length <= 500).map(post => [post.path, post.title]));
        catalogUntil = now() + 60 * 60000;
        return catalog;
      } catch { catalogUntil = now() + TTL; return catalog || {}; }
      finally { catalogPending = null; }
    })();
    return catalogPending;
  }
  return async function report(params, env = process.env) {
    const range = trafficOptions(params, now()), config = connection(env);
    if (config.missing) return { configured: false, missing: config.missing };
    const key = JSON.stringify([config.account, config.site, createHash('sha256').update(config.token).digest('hex'), range.start, range.scope, range.path]);
    const cached = cache.get(key);
    if (cached && now() < cached.expires) return cached.value;
    if (pending.has(key)) return pending.get(key);
    if (pending.size >= 6) throw new HttpError(429, 'An analytics report is already loading. Wait a moment and try again.');
    const task = (async () => {
      const filter = { datetime_geq: range.start, datetime_lt: range.end, siteTag: config.site, requestHost_in: ['nateoconnell.com', 'www.nateoconnell.com'] };
      if (range.scope === 'blog') { filter.requestPath_like = '/blog/%'; filter.requestPath_neq = '/blog/'; }
      if (range.path) filter.requestPath = range.path;
      let account;
      try {
        const response = await fetchImpl(ENDPOINT, { method: 'POST', signal: AbortSignal.timeout(20000), redirect: 'error',
          headers: { Authorization: `Bearer ${config.token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: QUERY, variables: { account: config.account, filter } }) });
        if (!response.ok) throw new Error('Provider request failed');
        const data = await readJson(response);
        if (data.errors?.length || data.data?.viewer?.accounts?.length !== 1) throw new Error('Provider query failed');
        account = summarizeTraffic(data.data.viewer.accounts[0], range);
      } catch {
        throw new HttpError(502, 'Cloudflare could not provide this report. Check the account ID, Web Analytics site tag, and token with Account Analytics: Read permission. No counts have been substituted.');
      }
      const titles = await postCatalog();
      for (const page of account.pages) page.title = titles[page.path] || (page.path === '/' ? 'Homepage' : page.path === '/blog/' ? 'Blog index' : page.path);
      if (range.scope === 'blog' && !range.path && !account.pagesLimited) {
        const seen = new Set(account.pages.map(page => page.path));
        for (const [path, title] of Object.entries(titles)) if (!seen.has(path)) account.pages.push({ path, title, ...blank() });
      }
      const value = { configured: true, source: 'Cloudflare Web Analytics', fetchedAt: new Date(now()).toISOString(), range, ...account };
      if (cache.size >= 24) cache.delete(cache.keys().next().value);
      cache.set(key, { expires: now() + TTL, value });
      return value;
    })();
    pending.set(key, task);
    try { return await task; } finally { pending.delete(key); }
  };
}

export const trafficReport = createTrafficService();
