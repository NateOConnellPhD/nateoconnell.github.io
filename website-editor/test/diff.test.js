import test from 'node:test';
import assert from 'node:assert/strict';
import { lineDiff, wordDiff, renderDiff } from '../public/diff.js';

function restores(before, after, diff) {
  assert.equal(diff.filter(row => row.type !== 'add').map(row => row.text).join(''), before);
  assert.equal(diff.filter(row => row.type !== 'remove').map(row => row.text).join(''), after);
}
test('line changes preserve both versions, line numbers, blank lines and final newlines', () => {
  for (const [before, after] of [['', 'New page\n'], ['Old page\n', ''], ['one\ntwo\nthree\n', 'one\nnew two\nthree\n'], ['same\n', 'same'], ['a\r\n\r\nb', 'a\r\nnew\r\nb']]) {
    const diff = lineDiff(before, after); restores(before, after, diff);
    assert.deepEqual(diff.filter(row => row.oldLine).map(row => row.oldLine), Array.from({ length: diff.filter(row => row.oldLine).length }, (_, i) => i + 1));
    assert.deepEqual(diff.filter(row => row.newLine).map(row => row.newLine), Array.from({ length: diff.filter(row => row.newLine).length }, (_, i) => i + 1));
  }
});
test('word highlights isolate changed wording and preserve Markdown, TeX and Unicode', () => {
  const before = 'I study variance in $\\hat{y}$ — Nate.', after = 'I study uncertainty in $\\hat{y}$ — Nate.';
  const diff = wordDiff(before, after); restores(before, after, diff);
  assert.deepEqual(diff.filter(row => row.type !== 'equal'), [{ type: 'remove', text: 'variance' }, { type: 'add', text: 'uncertainty' }]);
});
test('large rewrites and repeated lines remain exact without an unbounded comparison matrix', () => {
  const before = 'old\n'.repeat(10000), after = 'new\n'.repeat(10000);
  restores(before, after, lineDiff(before, after));
  let seed = 24;
  const random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed % 5; };
  for (let i = 0; i < 100; i++) {
    const left = Array.from({ length: random() * 5 }, () => random() + '\n').join('');
    const right = Array.from({ length: random() * 5 }, () => random() + '\n').join('');
    restores(left, right, lineDiff(left, right));
  }
});
test('review renders source as text, with explicit removal and addition markers', t => {
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.textContent = ''; }
    append(...children) { this.children.push(...children); }
    setAttribute() {}
    set innerHTML(value) { assert.fail('Source must never become executable HTML'); }
  }
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'document');
  globalThis.document = { createElement: tag => new Element(tag) };
  t.after(() => { if (previous) Object.defineProperty(globalThis, 'document', previous); else delete globalThis.document; });
  const root = renderDiff('<script>old()</script>\n', '<script>new()</script>\n');
  const all = node => [node, ...node.children.flatMap(all)];
  const nodes = all(root);
  assert.ok(nodes.some(node => node.className === 'diff-line diff-remove'));
  assert.ok(nodes.some(node => node.className === 'diff-line diff-add'));
  assert.ok(nodes.some(node => node.tag === 'del' && node.textContent === 'old'));
  assert.ok(nodes.some(node => node.tag === 'ins' && node.textContent === 'new'));
  assert.ok(!nodes.some(node => node.tag === 'script'));
});
