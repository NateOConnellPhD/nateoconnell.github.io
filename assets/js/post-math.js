// Kramdown protects TeX while processing Markdown, producing these delimiters.
// Code blocks are deliberately excluded by KaTeX's auto-render extension.
if (globalThis.renderMathInElement) {
  for (const root of document.querySelectorAll('.article-body')) {
    // Compatibility with older Kramdown versions that emit math/tex scripts.
    for (const source of root.querySelectorAll('script[type^="math/tex"]')) {
      const display = source.type.includes('mode=display');
      const node = document.createElement(display ? 'div' : 'span');
      node.textContent = (display ? '\\[' : '\\(') + source.textContent + (display ? '\\]' : '\\)');
      source.replaceWith(node);
    }
    globalThis.renderMathInElement(root, {
      delimiters: [{ left: '\\(', right: '\\)', display: false }, { left: '\\[', right: '\\]', display: true }],
      throwOnError: false, trust: false, maxExpand: 1000
    });
  }
}
