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

test('date ranges include today in UTC and unsafe or unsupported filters are rejected', () => {
  const range = trafficOptions(params('days=7&scope=blog'), instant);
  assert.equal(range.start, '2026-11-14T00:00:00.000Z');
  assert.equal(range.end, '2026-11-20T14:30:00.000Z');
  for (const text of ['days=1000', 'scope=secret', 'scope=blog&page=/about/', 'scope=blog&page=/blog/', 'page=traffic', 'page=//other.test/']) assert.throws(() => trafficOptions(params(text), instant));
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
    ['?scope=blog&page=%2Fblog%2Fexample%2F', '/blog/example/'],
    ['?path=%2Fabout%2F', '/about/']
  ]) {
    const elements = new Map(), requests = [], addresses = [];
    const service = createTrafficService({ now: () => instant, fetchImpl: async () => { throw new Error('No external requests expected'); } });
    await runInNewContext(source, {
      URLSearchParams, AbortController, setTimeout, clearTimeout, location: { search },
      history: { replaceState: (_state, _unused, url) => addresses.push(url) },
      document: { getElementById: id => {
        if (!elements.has(id)) elements.set(id, { value: id === 'traffic-days' ? '7' : id === 'traffic-scope' ? 'site' : '', dataset: {}, addEventListener() {} });
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
  let time = instant;
  const calls = [];
  const service = createTrafficService({ now: () => time, fetchImpl: async (url, options) => {
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
  const service = createTrafficService({ now: () => instant, fetchImpl: async () => { requests++; return responses.shift()(); } });
  const setup = await service(params(''), {});
  assert.equal(setup.configured, false); assert.equal(setup.missing.length, 3); assert.equal(requests, 0);
  for (let i = 0; i < 5; i++) await assert.rejects(service(params(''), credentials), error => error.status === 502 && !error.message.includes('private diagnostic'));
  assert.equal(requests, 5);
});

test('an unavailable public catalog does not discard counts or retry on every different report', async () => {
  let catalogCalls = 0;
  const service = createTrafficService({ now: () => instant, fetchImpl: async url => {
    if (url.endsWith('/traffic-posts.json')) { catalogCalls++; return new Response('Not deployed', { status: 404 }); }
    return provider(groups());
  } });
  assert.equal((await service(params(''), credentials)).totals.all, 15);
  await service(params('scope=blog'), credentials);
  assert.equal(catalogCalls, 1);
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
