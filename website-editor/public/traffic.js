const $ = id => document.getElementById(id);
const node = (tag, text, className) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; };
const labels = { notFlagged: 'Not flagged as bots', bots: 'Detected bots', all: 'All recorded views', unclassified: 'Unclassified' };
const number = value => Math.round(value).toLocaleString();
const dateLabel = date => new Date(date + 'T00:00:00Z').toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
let report = null, controller = null, serial = 0, selectedPath = '', sort = 'notFlagged', descending = true;

function svgNode(tag, attributes = {}, text) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) el.setAttribute(key, value);
  if (text !== undefined) el.textContent = text;
  return el;
}

function chart() {
  const audience = $('traffic-audience').value, container = $('traffic-chart'); container.replaceChildren();
  const keys = audience === 'all' ? ['notFlagged', 'bots', 'unclassified'] : [audience];
  const legend = node('div', undefined, 'traffic-legend');
  for (const key of keys) if (key !== 'unclassified' || report.totals.unclassified || audience === 'unclassified') legend.append(node('span', labels[key], key));
  container.append(legend);
  const width = 1000, height = 240, left = 55, bottom = 205, top = 20, plotWidth = width - left - 20;
  const max = Math.max(1, ...report.daily.map(day => day[audience]));
  const svg = svgNode('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': `${labels[audience]} by day. Exact reported counts are in the Daily counts table.`, class: 'traffic-chart' });
  for (const part of max < 2 ? [0, 1] : [0, .5, 1]) {
    const y = bottom - part * (bottom - top);
    svg.append(svgNode('line', { x1: left, x2: width - 20, y1: y, y2: y, class: 'traffic-axis' }));
    svg.append(svgNode('text', { x: left - 9, y: y + 4, 'text-anchor': 'end' }, number(max * part)));
  }
  const step = plotWidth / report.daily.length, barWidth = Math.min(64, step * .68);
  report.daily.forEach((day, index) => {
    const x = left + step * (index + .5), group = svgNode('g'); let y = bottom;
    group.append(svgNode('title', {}, `${dateLabel(day.date)}: ${keys.map(key => `${number(day[key])} ${labels[key].toLowerCase()}`).join(', ')}`));
    for (const key of keys) {
      const size = day[key] / max * (bottom - top); y -= size;
      group.append(svgNode('rect', { x: x - barWidth / 2, y, width: barWidth, height: size, class: key === 'bots' ? 'traffic-bar-bot' : key === 'unclassified' ? 'traffic-bar-unknown' : 'traffic-bar' }));
    }
    svg.append(group);
    if (report.daily.length <= 7 || index === 0 || index === report.daily.length - 1 || index % 7 === 0) svg.append(svgNode('text', { x, y: 230, 'text-anchor': 'middle' }, dateLabel(day.date)));
  });
  container.append(svg);
}

function table(headers) {
  const el = node('table', undefined, 'traffic-table'), head = node('thead'), row = node('tr'), body = node('tbody');
  for (const [index, title] of headers.entries()) { const th = node('th', title, index ? 'traffic-number' : ''); th.scope = 'col'; row.append(th); }
  head.append(row); el.append(head, body); return { el, row, body };
}

function dailyTable() {
  const audience = $('traffic-audience').value, result = table(['Date (UTC)', labels[audience]]);
  for (const day of report.daily) { const row = node('tr'); row.append(node('td', dateLabel(day.date)), node('td', number(day[audience]), 'traffic-number')); result.body.append(row); }
  $('traffic-daily-table').replaceChildren(result.el);
}

function pages() {
  const query = $('traffic-search').value.trim().toLowerCase(), audience = $('traffic-audience').value;
  const columns = [['title', 'Page'], [audience, labels[audience]]];
  const rows = report.pages.filter(page => `${page.title} ${page.path}`.toLowerCase().includes(query)).sort((a, b) => {
    const value = sort === 'title' ? a.title.localeCompare(b.title) : a[audience] - b[audience];
    return (descending ? -value : value) || a.path.localeCompare(b.path);
  });
  const result = table(columns.map(([, label]) => label));
  columns.forEach(([key, label], index) => {
    const th = result.row.children[index], active = (sort === 'title') === (key === 'title');
    th.textContent = ''; if (active) th.setAttribute('aria-sort', descending ? 'descending' : 'ascending');
    const button = node('button', label + (active ? descending ? ' ↓' : ' ↑' : ''), 'traffic-sort'); button.type = 'button';
    button.addEventListener('click', () => { descending = sort === key ? !descending : key !== 'title'; sort = key; pages(); }); th.append(button);
  });
  for (const page of rows) {
    const row = node('tr'), name = node('td'), button = node('button', page.title, 'traffic-page-button'); button.type = 'button';
    button.addEventListener('click', () => { selectedPath = page.path; load(); }); name.append(button);
    if (page.title !== page.path) name.append(node('span', page.path, 'traffic-path'));
    row.append(name, node('td', number(page[audience]), 'traffic-number')); result.body.append(row);
  }
  $('traffic-pages-table').replaceChildren(rows.length ? result.el : node('p', query ? 'No pages match your search.' : 'No page records for this selection.', 'small'));
}

function render() {
  $('traffic-report').hidden = false;
  $('traffic-focus').hidden = !report.range.path;
  if (report.range.path) {
    $('traffic-page-title').textContent = report.pages.find(page => page.path === report.range.path)?.title || report.range.path;
    $('traffic-page-link').href = `https://nateoconnell.com${report.range.path}`;
  }
  $('traffic-stats').replaceChildren();
  for (const key of ['all', 'notFlagged', 'bots', ...(report.totals.unclassified ? ['unclassified'] : [])]) {
    const card = node('section', undefined, 'traffic-stat');
    card.append(node('h2', labels[key]), node('strong', number(report.totals[key])));
    card.append(node('p', key === 'all' ? 'Page loads, including detected bots' : key === 'notFlagged' ? 'Not a verified human count' : key === 'bots' ? 'Flagged by Cloudflare' : 'No recognized bot classification'));
    $('traffic-stats').append(card);
  }
  $('traffic-pages-heading').textContent = report.range.scope === 'blog' ? 'Blog posts' : 'Pages';
  $('traffic-empty').hidden = report.totals.all !== 0;
  $('traffic-limited').hidden = !report.pagesLimited;
  $('traffic-freshness').textContent = `${report.source} · Queried ${new Date(report.fetchedAt).toLocaleString()}${report.sampled ? ' · Sampling reported' : ''}.`;
  chart(); dailyTable(); pages();
}

async function load() {
  controller?.abort(); const abort = new AbortController(); controller = abort; const id = ++serial;
  const params = new URLSearchParams({ days: $('traffic-days').value, scope: $('traffic-scope').value });
  if (selectedPath) params.set('page', selectedPath);
  history.replaceState(null, '', `/traffic.html?${params}`);
  $('traffic-status').textContent = 'Loading traffic…'; $('traffic-status').dataset.error = 'false';
  for (const key of ['traffic-report', 'traffic-setup', 'traffic-login']) $(key).hidden = true;
  $('traffic-reload').disabled = true;
  const timeout = setTimeout(() => abort.abort(), 35000);
  try {
    const response = await fetch(`/api/traffic?${params}`, { credentials: 'same-origin', cache: 'no-store', signal: abort.signal });
    if (id !== serial) return;
    if (response.status === 401) { $('traffic-login').hidden = false; $('traffic-controls').hidden = true; $('traffic-status').textContent = ''; return; }
    const result = await response.json();
    if (id !== serial) return;
    if (!response.ok) throw new Error(result.error || 'Traffic could not be loaded.');
    if (!result.configured) {
      $('traffic-setup').hidden = false; $('traffic-controls').hidden = true; $('traffic-status').textContent = '';
      $('traffic-missing').textContent = `Add these environment variables in Vercel: ${result.missing.join(', ')}.`; return;
    }
    $('traffic-controls').hidden = false; report = result; render(); $('traffic-status').textContent = '';
  } catch (error) {
    if (id !== serial) return;
    $('traffic-status').dataset.error = 'true';
    $('traffic-status').textContent = error.name === 'AbortError' ? 'The report took too long to load. Use Reload report to try again.' : `${error.message} Use Reload report to try again.`;
  } finally { clearTimeout(timeout); if (id === serial) $('traffic-reload').disabled = false; }
}

const params = new URLSearchParams(location.search);
if (['1', '7', '28'].includes(params.get('days'))) $('traffic-days').value = params.get('days');
if (params.get('scope') === 'blog') $('traffic-scope').value = 'blog';
// Preserve existing dashboard links, but send only `page` to the API.
selectedPath = params.get('page') ?? params.get('path') ?? '';
$('traffic-controls').addEventListener('submit', event => event.preventDefault());
for (const key of ['traffic-days', 'traffic-scope']) $(key).addEventListener('change', () => { selectedPath = ''; $('traffic-search').value = ''; load(); });
$('traffic-audience').addEventListener('change', () => { if (report) { sort = $('traffic-audience').value; descending = true; chart(); dailyTable(); pages(); } });
$('traffic-search').addEventListener('input', () => { if (report) pages(); });
$('traffic-back').addEventListener('click', () => { selectedPath = ''; load(); });
$('traffic-reload').addEventListener('click', load);
load();
