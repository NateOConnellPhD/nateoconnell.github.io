// Bounded LCS: normal edits get a compact diff; large rewrites remain exact
// without allocating a matrix proportional to the whole file squared.
function sequence(before, after, budget = 1000000) {
  let start = 0, end = 0;
  while (start < before.length && start < after.length && before[start] === after[start]) start++;
  while (end < before.length - start && end < after.length - start && before.at(-end - 1) === after.at(-end - 1)) end++;
  const result = before.slice(0, start).map(text => ({ type: 'equal', text }));
  const left = before.slice(start, before.length - end), right = after.slice(start, after.length - end);
  if ((left.length + 1) * (right.length + 1) > budget) {
    for (const text of left) result.push({ type: 'remove', text });
    for (const text of right) result.push({ type: 'add', text });
  } else {
    const width = right.length + 1, table = new Uint32Array((left.length + 1) * width);
    for (let i = left.length - 1; i >= 0; i--) for (let j = right.length - 1; j >= 0; j--) {
      table[i * width + j] = left[i] === right[j] ? 1 + table[(i + 1) * width + j + 1]
        : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
    }
    let i = 0, j = 0;
    while (i < left.length || j < right.length) {
      if (i < left.length && j < right.length && left[i] === right[j]) { result.push({ type: 'equal', text: left[i++] }); j++; }
      else if (i < left.length && (j === right.length || table[(i + 1) * width + j] >= table[i * width + j + 1])) result.push({ type: 'remove', text: left[i++] });
      else result.push({ type: 'add', text: right[j++] });
    }
  }
  return result.concat(before.slice(before.length - end).map(text => ({ type: 'equal', text })));
}

export function lineDiff(before, after) {
  const lines = value => (value || '').match(/[^\n]*\n|[^\n]+$/g) || [];
  let oldLine = 0, newLine = 0;
  return sequence(lines(before), lines(after)).map(row => ({ ...row,
    oldLine: row.type === 'add' ? null : ++oldLine,
    newLine: row.type === 'remove' ? null : ++newLine
  }));
}
export function wordDiff(before, after) {
  const tokens = value => value.match(/\s+|[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]/gu) || [];
  return sequence(tokens(before), tokens(after), 20000);
}

const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const lineText = text => text.replace(/\r?\n$/, '');
export function renderDiff(before, after) {
  const rows = lineDiff(before, after), root = node('section', undefined, 'source-diff');
  const added = rows.filter(row => row.type === 'add').length, removed = rows.filter(row => row.type === 'remove').length;
  root.append(node('p', added || removed ? `+${added} added · −${removed} removed · Green adds text; red removes text.` : 'No text changes.', 'diff-legend'));
  if (!added && !removed) return root;
  const body = node('div', undefined, 'diff-body'); body.tabIndex = 0;
  body.setAttribute('role', 'region'); body.setAttribute('aria-label', 'Source changes with old and new line numbers');
  root.append(body);
  let rendered = 0;
  function rowElement(row, tokens) {
    const line = node('div', undefined, 'diff-line diff-' + row.type);
    for (const text of [row.oldLine ?? '', row.newLine ?? '', { equal: ' ', remove: '−', add: '+' }[row.type]]) line.append(node('span', String(text), 'diff-gutter'));
    const code = node('code');
    if (tokens) for (const token of tokens) {
      if (token.type !== 'equal' && token.type !== row.type) continue;
      code.append(node(token.type === 'equal' ? 'span' : row.type === 'add' ? 'ins' : 'del', token.text));
    } else code.textContent = lineText(row.text);
    if (!row.text.endsWith('\n')) code.append(node('span', ' ⏎ No newline at end of file', 'diff-eof'));
    line.append(code); body.append(line); rendered++;
  }
  for (let i = 0; i < rows.length;) {
    let end = i + 1;
    while (end < rows.length && rows[end].type === rows[i].type) end++;
    const group = rows.slice(i, end);
    if (group[0].type === 'equal' && group.length > 8) {
      const leading = i === 0 ? 0 : 3, trailing = end === rows.length ? 0 : 3;
      group.slice(0, leading).forEach(row => rowElement(row));
      const hidden = group.slice(leading, group.length - trailing);
      const details = node('details', undefined, 'diff-context');
      details.append(node('summary', `${hidden.length} unchanged lines · expand`), node('pre', hidden.map(row => row.text).join('')));
      body.append(details); group.slice(group.length - trailing).forEach(row => rowElement(row));
    } else if (rendered + group.length > 3000) {
      // Keep every changed byte available without creating thousands of nodes.
      const block = node('details', undefined, 'diff-block diff-' + group[0].type);
      block.append(node('summary', `${group.length} ${group[0].type === 'add' ? 'added' : group[0].type === 'remove' ? 'removed' : 'unchanged'} lines · expand`), node('pre', group.map(row => row.text).join('')));
      body.append(block);
    } else {
      let paired = [];
      if (group[0].type === 'remove' && rows[end]?.type === 'add') {
        let next = end; while (rows[next]?.type === 'add') paired.push(rows[next++]);
      } else if (group[0].type === 'add' && rows[i - 1]?.type === 'remove') {
        let prev = i - 1; while (rows[prev]?.type === 'remove') prev--;
        paired = rows.slice(prev + 1, Math.min(i, prev + 1 + group.length));
      }
      group.forEach((row, index) => {
        const other = paired[index];
        const tokens = other ? wordDiff(lineText(row.type === 'remove' ? row.text : other.text), lineText(row.type === 'add' ? row.text : other.text)) : null;
        rowElement(row, tokens);
      });
    }
    i = end;
  }
  return root;
}
