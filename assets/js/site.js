/* Progressive enhancement: all content and links work without JavaScript. */
document.querySelectorAll('[data-filter-list]').forEach((list) => {
  const entries = [...list.querySelectorAll('[data-entry]')];
  const buttons = [...list.querySelectorAll('[data-filter]')];
  const search = list.querySelector('[data-search-input]');
  const tags = list.querySelector('[data-tag-select]');
  const empty = list.querySelector('[data-no-results]');
  const count = list.querySelector('[data-result-count]');
  let kind = 'all';

  const update = () => {
    const query = (search?.value || '').trim().toLocaleLowerCase();
    const topic = tags?.value || '';
    let visible = 0;
    entries.forEach((entry) => {
      const matchesKind = kind === 'all' || entry.dataset.kind === kind;
      const matchesText = (entry.dataset.search || '').toLocaleLowerCase().includes(query);
      const matchesTag = !topic || (entry.dataset.tags || '').split('|').includes(topic);
      entry.hidden = !(matchesKind && matchesText && matchesTag);
      if (!entry.hidden) visible += 1;
    });
    empty.hidden = visible !== 0 || entries.length === 0;
    count.textContent = `${visible} ${visible === 1 ? 'entry' : 'entries'} shown`;
    buttons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.filter === kind)));
  };

  buttons.forEach((button) => button.addEventListener('click', () => {
    kind = button.dataset.filter;
    update();
  }));
  search?.addEventListener('input', update);
  tags?.addEventListener('change', update);
  if (tags) {
    const requested = new URLSearchParams(window.location.search).get('tag');
    if ([...tags.options].some((option) => option.value === requested)) tags.value = requested;
  }
  list.querySelector('[data-filter-controls]').hidden = false;
  update();
});
