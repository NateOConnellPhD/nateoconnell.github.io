// A deliberately small, DOM-only Markdown preview. Source HTML is always text.
// The actual website uses Jekyll/Kramdown for its final rendering.
export function linkTarget(value) {
  if (/^\/(?!\/)[^\s\\]*$/.test(value)) return `https://nateoconnell.com${value}`;
  try { const url = new URL(value); if (['https:', 'http:', 'mailto:'].includes(url.protocol)) return url.href; } catch { /* plain text */ }
  return null;
}
export function inline(parent, text, imageResolver, depth = 0) {
  if (depth > 4) { parent.append(document.createTextNode(text)); return; }
  const pattern = /(!?\[([^\]\n]*)\]\(([^\s)]+)\)|\*\*([^*\n]+)\*\*|\*([^*\n]+)\*|`([^`\n]+)`)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    parent.append(document.createTextNode(text.slice(last, match.index)));
    if (match[3]) {
      const target = linkTarget(match[3]);
      if (match[0].startsWith('!')) {
        const img = document.createElement('img'); img.alt = match[2]; img.loading = 'lazy';
        parent.append(img); imageResolver?.(img, match[3]);
      } else if (target) {
        const a = document.createElement('a'); a.href = target; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = match[2]; parent.append(a);
      } else parent.append(document.createTextNode(match[0]));
    } else {
      const tag = match[4] ? 'strong' : match[5] ? 'em' : 'code';
      const node = document.createElement(tag); node.textContent = match[4] || match[5] || match[6]; parent.append(node);
    }
    last = match.index + match[0].length;
  }
  parent.append(document.createTextNode(text.slice(last)));
}
export function markdown(parent, text, imageResolver) {
  const lines = String(text).replace(/\r/g, '').split('\n');
  let paragraph = [], list = null, code = null;
  const flush = () => { if (paragraph.length) { const p = document.createElement('p'); inline(p, paragraph.join('\n'), imageResolver); parent.append(p); paragraph = []; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^```/.test(line)) {
      flush(); list = null;
      if (code !== null) { const pre = document.createElement('pre'); const child = document.createElement('code'); child.textContent = code.join('\n'); pre.append(child); parent.append(pre); code = null; }
      else code = [];
      continue;
    }
    if (code !== null) { code.push(line); continue; }
    if (!line.trim()) { flush(); list = null; continue; }
    if (/^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || '') && line.includes('|')) {
      flush(); list = null; const table = document.createElement('table');
      const cells = row => row.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|');
      const header = document.createElement('tr'); for (const cell of cells(line)) { const th = document.createElement('th'); inline(th, cell.trim(), imageResolver); header.append(th); } table.append(header); i++;
      while ((lines[i + 1] || '').includes('|')) { const tr = document.createElement('tr'); for (const cell of cells(lines[++i])) { const td = document.createElement('td'); inline(td, cell.trim(), imageResolver); tr.append(td); } table.append(tr); }
      parent.append(table); continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    const item = line.match(/^\s*(?:([-*])|\d+\.)\s+(.+)$/);
    if (heading) { flush(); list = null; const h = document.createElement(`h${heading[1].length}`); inline(h, heading[2], imageResolver); parent.append(h); }
    else if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { flush(); list = null; parent.append(document.createElement('hr')); }
    else if (line.startsWith('> ')) { flush(); list = null; const quote = document.createElement('blockquote'); inline(quote, line.slice(2), imageResolver); parent.append(quote); }
    else if (item) { flush(); const tag = item[1] ? 'UL' : 'OL'; if (!list || list.tagName !== tag) { list = document.createElement(tag); parent.append(list); } const li = document.createElement('li'); inline(li, item[2], imageResolver); list.append(li); }
    else { list = null; paragraph.push(line); }
  }
  flush();
  if (code !== null) { const pre = document.createElement('pre'); pre.textContent = code.join('\n'); parent.append(pre); }
}
