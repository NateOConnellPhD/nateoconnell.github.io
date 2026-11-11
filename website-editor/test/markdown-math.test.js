import test from 'node:test';
import assert from 'node:assert/strict';
import { markdown } from '../public/markdown.js';
import { validateDocument } from '../lib/content.js';

class Node {
  constructor(tag, text = '') { this.tagName = tag.toUpperCase(); this.children = []; this.text = text; }
  append(...children) { this.children.push(...children); }
  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return this.text + this.children.map(node => node.textContent).join(''); }
}
const collect = (node, name) => [...(node.className?.includes(name) ? [node] : []), ...node.children.flatMap(child => collect(child, name))];
test('Markdown preserves TeX, distinguishes inline/display equations, and keeps code literal', () => {
  const previous = globalThis.document;
  const head = new Node('head');
  globalThis.document = { head, createElement: tag => new Node(tag), createTextNode: text => new Node('#text', text) };
  try {
    const root = new Node('article');
    const source = String.raw`An estimate $$\hat{\theta}_i^*$$ and **bold** text.

$$
\begin{aligned}
\hat{\theta} &= \frac{1}{n} \sum_{i=1}^n x_i \\
v &= \sigma^2
\end{aligned}
$$

After the equation.

Inline code: ` + '`$$x$$`' + '\n\n```tex\n$$literal$$\n```';
    markdown(root, source);
    const equations = collect(root, 'math-source');
    assert.equal(equations.length, 2);
    assert.equal(equations[0].tagName, 'SPAN');
    assert.equal(equations[0].textContent, String.raw`\hat{\theta}_i^*`);
    assert.equal(equations[1].tagName, 'DIV');
    assert.match(equations[1].textContent, /\\begin\{aligned\}/);
    assert.ok(root.textContent.includes('After the equation.'));
    assert.ok(root.textContent.includes('$$literal$$'));
    assert.equal(head.children.length, 2, 'one lazy stylesheet/script load for all equations');
    assert.ok(head.children.every(node => node.integrity.startsWith('sha384-')));
    const document = validateDocument({ kind: 'post', path: '_posts/2026-11-11-test.md', fields: {}, body: source });
    assert.equal(document.body, source, 'saving preserves the Markdown/TeX source');
  } finally { globalThis.document = previous; }
});
