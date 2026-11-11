// Only load the pinned renderer when a preview actually contains equations.
let loading;
function loadMath() {
  if (!loading) loading = Promise.all([
    ['link', 'https://cdn.jsdelivr.net/npm/katex@0.19.1/dist/katex.min.css', 'sha384-WwGtaC6ywCHxA5cstpj/3+xIZvTez8dq2IcBQaXRkenHZ7FVVq1ZROtURwfbtTlG'],
    ['script', 'https://cdn.jsdelivr.net/npm/katex@0.19.1/dist/katex.min.js', 'sha384-a1WQdjRj162i159OYq041X6I4K8NenkrI09LlPmiHg0YOb7CR+wJOraXwK9abpnE']
  ].map(([tag, url, integrity]) => new Promise((resolve, reject) => {
    const element = document.createElement(tag);
    if (tag === 'link') { element.rel = 'stylesheet'; element.href = url; }
    else { element.src = url; element.async = true; }
    element.integrity = integrity; element.crossOrigin = 'anonymous'; element.referrerPolicy = 'no-referrer';
    element.onload = resolve; element.onerror = () => { element.remove(); reject(new Error('Equation preview unavailable; your TeX source is preserved.')); };
    document.head.append(element);
  }))).catch(error => { loading = null; throw error; });
  return loading;
}
export function equation(source, display = false) {
  const node = document.createElement(display ? 'div' : 'span');
  node.className = display ? 'math-source math-display' : 'math-source';
  node.textContent = source;
  loadMath().then(() => {
    // A removed preview should not reappear after the renderer loads.
    if (node.isConnected) globalThis.katex.render(source, node, { displayMode: display, throwOnError: false, trust: false, maxExpand: 1000 });
  }).catch(error => { node.title = error.message; });
  return node;
}
