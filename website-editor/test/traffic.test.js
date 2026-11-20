import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import { createTrafficService, pagePath, trafficOptions, summarizeTraffic } from '../lib/traffic.js';
import { configuration, seal, unseal, STATE, SESSION } from '../lib/security.js';
import { handle } from '../api/index.js';

const instant = Date.parse('2026-11-20T14:30:00Z');
const credentials = { CLOUDFLARE_ACCOUNT_ID: 'a'.repeat(32), CLOUDFLARE_WEB_ANALYTICS_SITE_TAG: 'b'.repeat(32), CLOUDFLARE_ANALYTICS_TOKEN: 'read-only-test-token' };
const params = text => new URLSearchParams(text);
const row = (count, bot, extra = {}, sampleInterval = 1) => ({ count, dimensions: { bot, ...extra }, avg: { sampleInterval } });
const groups = () => ({
  totals: [row(10, 0, {}, 4), row(3, 1), row(2, null)],
  daily: [row(10, 0, { date: '2026-11-20' }, 4), row(3, 1, { date: '2026-11-20' }), row(2, null, { date: '2026-11-20' })],
  pages: [row(10, 0, { requestPath: '/blog/2026/11/20/example/' }), row(3, 1, { requestPath: '/blog/2026/11/20/example/' }), row(2, null, { requestPath: '/' })]
});
const provider = account => Response.json({ data: { viewer: { accounts: [account] } } });
const limitsResponse = (overrides = {}) => provider({ settings: { rumPageloadEventsAdaptiveGroups: { enabled: true, maxDuration: 30 * 86400, notOlderThan: 180 * 86400, ...overrides } } });
const isLimits = options => Boolean(options?.body && JSON.parse(options.body).query.includes('WebsiteTrafficLimits'));

test('date ranges include today in UTC and unsafe or unsupported filters are rejected', () => {
  const range = trafficOptions(params('days=7&scope=blog'), instant);
  assert.equal(range.start, '2026-11-14T00:00:00.000Z');
  assert.equal(range.end, '2026-11-20T14:30:00.000Z');
  for (const days of [1, 2, 14, 45, 90, 180, 1000]) assert.equal(trafficOptions(params(`days=${days}`), instant).days, days);
  assert.equal(trafficOptions(params('days=45'), instant).start, '2026-10-07T00:00:00.000Z');
  for (const text of ['days=', 'days=0', 'days=-1', 'days=2.5', 'days=1e2', 'days=no', 'days=9007199254740991', 'scope=secret', 'scope=blog&page=/about/', 'scope=blog&page=/blog/', 'page=traffic', 'page=//other.test/']) assert.throws(() => trafficOptions(params(text), instant));
  for (const path of ['https://other.test/', '//other.test/', '/a/../b', '/%2e%2e/', '/a?secret=1', '/a#b', '/a\\b']) assert.equal(pagePath(path), null);
  assert.equal(pagePath('/blog/caf%C3%A9/'), '/blog/caf%C3%A9/');
  assert.equal(pagePath('/blog/café/'), '/blog/café/');
});

test('Vercel route parameters do not become page filters', () => {
  const rewritten = params('route=traffic&path=traffic&days=28&scope=site');
  assert.equal(trafficOptions(rewritten, instant).path, '');
  rewritten.set('page', '/about/');
  assert.equal(trafficOptions(rewritten, instant).path, '/about/');
  rewritten.set('page', 'traffic');
  assert.throws(() => trafficOptions(rewritten, instant), error => error.status === 400);
});

test('dashboard uses a separate page parameter and preserves existing page links', async () => {
  const source = await readFile(new URL('../public/traffic.js', import.meta.url), 'utf8');
  for (const [search, selected] of [
    ['?days=28&scope=site', ''],
    ['?days=45&scope=site', ''],
    ['?days=90&scope=blog&page=%2Fblog%2Fexample%2F', '/blog/example/'],
    ['?scope=blog&page=%2Fblog%2Fexample%2F', '/blog/example/'],
    ['?path=%2Fabout%2F', '/about/']
  ]) {
    const elements = new Map(), requests = [], addresses = [];
    const service = createTrafficService({ now: () => instant, fetchImpl: async () => { throw new Error('No external requests expected'); } });
    await runInNewContext(source, {
      URLSearchParams, AbortController, setTimeout, clearTimeout, location: { search },
      history: { replaceState: (_state, _unused, url) => addresses.push(url) },
      document: { getElementById: id => {
        if (!elements.has(id)) elements.set(id, { value: id === 'traffic-days' ? '7' : id === 'traffic-scope' ? 'site' : '', dataset: {}, addEventListener() {}, reportValidity: () => true });
        return elements.get(id);
      } },
      fetch: async url => {
        const query = new URL(url, 'https://editor.example.com').searchParams;
        requests.push(new URLSearchParams(query));
        query.set('route', 'traffic'); query.set('path', 'traffic');
        return Response.json(await service(query, {}));
      }
    });
    assert.equal(requests.length, 1);
    for (const query of [requests[0], new URL(addresses[0], 'https://editor.example.com').searchParams]) {
      assert.equal(query.get('page') || '', selected);
      assert.equal(query.has('path'), false);
      assert.equal(query.get('days'), new URLSearchParams(search).get('days') || '7');
    }
    assert.equal(elements.get('traffic-status').dataset.error, 'false');
    assert.equal(elements.get('traffic-setup').hidden, false);
  }
});

test('bot categories stay separate and weighted counts are not multiplied by sampling', () => {
  const report = summarizeTraffic(groups(), trafficOptions(params(''), instant));
  assert.deepEqual(report.totals, { all: 15, notFlagged: 10, bots: 3, unclassified: 2 });
  assert.equal(report.daily.length, 7);
  assert.equal(report.daily[0].all, 0);
  assert.equal(report.daily.at(-1).all, 15);
  assert.equal(report.pages[0].all, 13);
  assert.equal(report.sampled, true);
  assert.equal(report.pagesLimited, false);
  const empty = { totals: [], daily: [], pages: [] };
  assert.equal(summarizeTraffic(empty, trafficOptions(params('days=1'), Date.parse('2026-11-20T00:00:00Z'))).daily.length, 1);
  assert.equal(summarizeTraffic({ ...empty, pages: Array.from({ length: 1000 }, () => row(1, 0, { requestPath: '/' })) }, trafficOptions(params(''), instant)).pagesLimited, true);
  assert.throws(() => summarizeTraffic({ ...empty, totals: [row(-1, 0)] }, trafficOptions(params(''), instant)));
});

test('reports coalesce and cache; filters stay on this site and blog titles include zero-view posts', async () => {
  let time = instant, limitCalls = 0;
  const calls = [];
  const service = createTrafficService({ now: () => time, fetchImpl: async (url, options) => {
    if (options && isLimits(options)) { limitCalls++; return limitsResponse(); }
    calls.push({ url, options });
    if (url.endsWith('/traffic-posts.json')) return Response.json({ posts: [
      { path: '/blog/2026/11/20/example/', title: 'A real post' },
      { path: '/blog/2026/11/20/quiet/', title: 'No recorded views yet' },
      { path: '//other.test/', title: 'Invalid' }
    ] });
    return provider(groups());
  } });
  const query = params('scope=blog&days=7');
  const [first, second] = await Promise.all([service(query, credentials), service(query, credentials)]);
  assert.deepEqual(first, second);
  assert.equal(calls.length, 2);
  assert.equal(first.pages.find(page => page.path.endsWith('/example/')).title, 'A real post');
  assert.equal(first.pages.find(page => page.path.endsWith('/quiet/')).all, 0);
  assert.ok(!JSON.stringify(first).includes(credentials.CLOUDFLARE_ANALYTICS_TOKEN));
  const body = JSON.parse(calls[0].options.body);
  assert.deepEqual(body.variables.filter.requestHost_in, ['nateoconnell.com', 'www.nateoconnell.com']);
  assert.equal(body.variables.filter.requestPath_like, '/blog/%');
  assert.equal(body.variables.filter.requestPath_neq, '/blog/');
  assert.equal(body.variables.filter.siteTag, credentials.CLOUDFLARE_WEB_ANALYTICS_SITE_TAG);
  assert.ok(!body.query.includes('visits'));
  await service(query, credentials); assert.equal(calls.length, 2);
  time += 5 * 60000 + 1;
  await service(query, credentials); assert.equal(calls.length, 3);
  await service(params('route=traffic&path=traffic&page=/about/&days=1'), credentials);
  assert.equal(JSON.parse(calls.at(-1).options.body).variables.filter.requestPath, '/about/');
  assert.equal(limitCalls, 1);
});

test('missing setup makes no requests; provider failures are not zero reports or cached successes', async () => {
  let requests = 0;
  const responses = [
    () => Response.json({ errors: [{ message: 'private diagnostic' }] }),
    () => Response.json({}, { status: 403 }),
    () => Response.json({ data: { viewer: { accounts: [] } } }),
    () => provider({ totals: [row(-1, 0)], daily: [], pages: [] }),
    () => { throw new Error('request timed out'); }
  ];
  const service = createTrafficService({ now: () => instant, fetchImpl: async (_url, options) => {
    if (isLimits(options)) return limitsResponse();
    requests++; return responses.shift()();
  } });
  const setup = await service(params(''), {});
  assert.equal(setup.configured, false); assert.equal(setup.missing.length, 3); assert.equal(requests, 0);
  for (let i = 0; i < 5; i++) await assert.rejects(service(params(''), credentials), error => error.status === 502 && !error.message.includes('private diagnostic'));
  assert.equal(requests, 5);
});

test('an unavailable public catalog does not discard counts or retry on every different report', async () => {
  let catalogCalls = 0;
  const service = createTrafficService({ now: () => instant, fetchImpl: async (url, options) => {
    if (isLimits(options)) return limitsResponse();
    if (url.endsWith('/traffic-posts.json')) { catalogCalls++; return new Response('Not deployed', { status: 404 }); }
    return provider(groups());
  } });
  assert.equal((await service(params(''), credentials)).totals.all, 15);
  await service(params('scope=blog'), credentials);
  assert.equal(catalogCalls, 1);
});

test('a custom 90-day report combines non-overlapping provider windows without losing days or bot classes', async () => {
  const windows = []; let limitCalls = 0;
  const page = '/blog/2026/11/20/example/';
  const service = createTrafficService({ now: () => instant, fetchImpl: async (url, options) => {
    if (url.endsWith('/traffic-posts.json')) return Response.json({ posts: [] });
    if (isLimits(options)) { limitCalls++; return limitsResponse(); }
    const { filter } = JSON.parse(options.body).variables;
    windows.push(filter);
    const from = Date.parse(filter.datetime_geq), until = Date.parse(filter.datetime_lt);
    const dates = [];
    for (let date = Math.floor(from / 86400000) * 86400000; date < until; date += 86400000) {
      if (date + 43200000 >= from && date + 43200000 < until) dates.push(new Date(date).toISOString().slice(0, 10));
    }
    return provider({
      totals: [row(dates.length, 0), row(dates.length * 2, 1), row(dates.length * 3, null)],
      daily: dates.flatMap(date => [row(1, 0, { date }), row(2, 1, { date }), row(3, null, { date }, 4)]),
      pages: [row(dates.length, 0, { requestPath: page }), row(dates.length * 2, 1, { requestPath: page }), row(dates.length * 3, null, { requestPath: page })]
    });
  } });
  const request = params(`days=90&scope=blog&page=${page}`);
  const [report, matching] = await Promise.all([service(request, credentials), service(request, credentials)]);
  assert.deepEqual(report, matching);
  assert.equal(windows.length, 3); assert.equal(limitCalls, 1);
  assert.equal(windows[0].datetime_geq, report.range.start);
  assert.equal(windows.at(-1).datetime_lt, report.range.end);
  for (let i = 0; i < windows.length; i++) {
    assert.ok(Date.parse(windows[i].datetime_lt) - Date.parse(windows[i].datetime_geq) <= 30 * 86400000);
    if (i) assert.equal(windows[i].datetime_geq, windows[i - 1].datetime_lt);
    assert.equal(windows[i].requestPath, page);
    assert.equal(windows[i].requestPath_like, '/blog/%');
  }
  assert.deepEqual(report.totals, { all: 540, notFlagged: 90, bots: 180, unclassified: 270 });
  assert.equal(report.daily.length, 90); assert.ok(report.daily.every(day => day.all === 6));
  assert.equal(report.pages.length, 1); assert.equal(report.pages[0].all, 540);
  assert.equal(report.pagesLimited, false); assert.equal(report.sampled, true);
  await service(request, credentials); assert.equal(windows.length, 3);
});

test('the actual provider retention is enforced with a useful maximum, not a preset ceiling', async () => {
  let requests = 0, time = instant, limitCalls = 0;
  const service = createTrafficService({ now: () => time, fetchImpl: async (url, options) => {
    if (url.endsWith('/traffic-posts.json')) return Response.json({ posts: [] });
    if (isLimits(options)) { limitCalls++; return limitsResponse({ notOlderThan: 120 * 86400 }); }
    requests++; return provider({ totals: [], daily: [], pages: [] });
  } });
  await assert.rejects(service(params('days=121'), credentials), error => error.status === 400 && error.message.includes('120 days'));
  assert.equal(requests, 0);
  const report = await service(params('days=120'), credentials);
  assert.equal(report.range.days, 120); assert.equal(report.daily.length, 120); assert.equal(requests, 4);
  assert.equal(limitCalls, 1);
  time += 86400000 + 1;
  await service(params('days=1'), credentials);
  assert.equal(limitCalls, 2);
});

test('long reports keep daily queries below their row limit and flag only truncated page windows', async () => {
  let reports = 0;
  const service = createTrafficService({ now: () => instant, fetchImpl: async (url, options) => {
    if (url.endsWith('/traffic-posts.json')) return Response.json({ posts: [] });
    if (isLimits(options)) return limitsResponse({ maxDuration: 180 * 86400 });
    const { filter } = JSON.parse(options.body).variables;
    assert.ok(Date.parse(filter.datetime_lt) - Date.parse(filter.datetime_geq) <= 60 * 86400000);
    reports++;
    return provider({ totals: [row(500, 0)], daily: [], pages: Array.from({ length: 500 }, (_, i) => row(1, 0, { requestPath: `/page-${i}/` })) });
  } });
  const report = await service(params('days=180'), credentials);
  assert.equal(reports, 3); assert.equal(report.pagesLimited, false);
  assert.equal(report.pages.length, 500); assert.equal(report.pages[0].all, 3);
});

test('failure in a later window does not return or cache a partial report', async () => {
  let reports = 0;
  const service = createTrafficService({ now: () => instant, fetchImpl: async (_url, options) => {
    if (isLimits(options)) return limitsResponse();
    reports++;
    if (reports % 2 === 0) return Response.json({ errors: [{ message: 'private provider diagnostic' }] });
    return provider({ totals: [row(5, 0)], daily: [], pages: [] });
  } });
  for (let i = 0; i < 2; i++) await assert.rejects(service(params('days=90'), credentials), error => error.status === 502 && !error.message.includes('private provider diagnostic'));
  assert.equal(reports, 4);
});

test('traffic route requires the owner session and does not open GitHub storage; sign-in return is allowlisted', async () => {
  const env = { APP_ORIGIN: 'https://editor.example.com', GITHUB_CLIENT_ID: 'test-client', GITHUB_CLIENT_SECRET: 'test-secret', ALLOWED_GITHUB_USER_ID: '123', SESSION_SECRET: 'ab'.repeat(32), DRAFT_REPOSITORY: 'NateOConnellPhD/editor-private' };
  const keys = [...Object.keys(env), ...Object.keys(credentials)], saved = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  const transport = globalThis.fetch;
  try {
    Object.assign(process.env, env);
    for (const key of Object.keys(credentials)) delete process.env[key];
    globalThis.fetch = async () => { throw new Error('No external requests expected'); };
    const config = configuration(env), url = `${config.origin}/api/traffic`;
    assert.equal((await handle(new Request(url))).status, 401);
    const headers = id => ({ Cookie: `${SESSION}=${seal({ id, token: 'github-test', csrf: 'test-csrf' }, 'session', config)}` });
    assert.equal((await handle(new Request(url, { headers: headers(456) }))).status, 401);
    const response = await handle(new Request(url, { headers: headers(123) }));
    assert.equal(response.status, 200); assert.equal((await response.json()).configured, false);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    const rewritten = `${config.origin}/api?route=traffic&path=traffic&days=28&scope=site`;
    assert.equal((await handle(new Request(rewritten))).status, 401);
    const routed = await handle(new Request(rewritten, { headers: headers(123) }));
    assert.equal(routed.status, 200); assert.equal((await routed.json()).configured, false);
    assert.equal((await handle(new Request(url, { method: 'POST', headers: { ...headers(123), Origin: config.origin, 'X-CSRF-Token': 'test-csrf' } }))).status, 405);
    for (const [value, expected] of [['/traffic.html', '/traffic.html'], ['https://other.test/', '/']]) {
      const auth = await handle(new Request(`${config.origin}/api/auth/start?returnTo=${encodeURIComponent(value)}`));
      const state = auth.headers.get('set-cookie').match(new RegExp(`${STATE}=([^;]+)`))[1];
      assert.equal(unseal(state, 'oauth', config).returnTo, expected);
    }
  } finally {
    globalThis.fetch = transport;
    for (const [key, value] of Object.entries(saved)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; }
  }
});

test('beacon is restricted to public production pages and respects browser privacy signals', async () => {
  const source = await readFile(new URL('../../assets/js/analytics.js', import.meta.url), 'utf8');
  function scripts({ host = 'nateoconnell.com', protocol = 'https:', pathname = '/', token = 'a'.repeat(32), framed = false, navigator = {} } = {}) {
    const appended = [], self = {};
    runInNewContext(source, { location: { hostname: host, protocol, pathname }, navigator, window: { top: framed ? {} : self, self }, document: {
      currentScript: { dataset: { beaconToken: token } }, createElement: () => ({ dataset: {} }), head: { append: item => appended.push(item) }
    } });
    return appended;
  }
  assert.equal(scripts().length, 1);
  assert.equal(scripts({ host: 'www.nateoconnell.com', pathname: '/blog/example/' }).length, 1);
  assert.equal(scripts()[0].src, 'https://static.cloudflareinsights.com/beacon.min.js');
  for (const config of [{ host: 'localhost' }, { host: 'nateoconnellgithubio-website-editor.vercel.app' }, { protocol: 'http:' }, { framed: true }, { token: '' }, { pathname: '/login/' }, { navigator: { doNotTrack: '1' } }, { navigator: { globalPrivacyControl: true } }]) assert.equal(scripts(config).length, 0);
});
