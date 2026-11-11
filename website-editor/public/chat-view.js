const $ = id => document.getElementById(id);

export function createChatView() {
  const scroll = $('chat-scroll'), input = $('chat-prompt');
  function project(open, focus = true) {
    if (open) conversations(false);
    $('project-panel').hidden = !open;
    $('app').classList.toggle('project-open', open);
    for (const id of ['project-open', 'chat-project-open']) $(id).setAttribute('aria-expanded', String(open));
    if (focus) (open ? $('project-close') : $('site-chat').hidden ? $('chat-menu') : $('chat-project-open')).focus();
  }
  function conversations(open) {
    if (open) project(false, false);
    $('app').classList.toggle('conversations-open', open);
    $('chat-menu').setAttribute('aria-expanded', String(open));
    if (open) $('chat-new').focus();
  }
  function resize() {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 180, window.innerHeight * .25)}px`;
  }
  function attachment() {
    const file = $('chat-reference').files[0];
    $('chat-attachment-name').textContent = file?.name || '';
    $('chat-attachment-remove').hidden = !file;
  }
  const nearBottom = () => scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop < 100;
  function jump() { scroll.scrollTop = scroll.scrollHeight; $('chat-jump').hidden = true; }
  function follow(wasNearBottom) { if (wasNearBottom) requestAnimationFrame(jump); }
  for (const id of ['project-open', 'chat-project-open', 'chat-changes-open']) $(id).addEventListener('click', () => project(true));
  $('project-close').addEventListener('click', () => project(false));
  $('chat-menu').addEventListener('click', () => conversations(!$('app').classList.contains('conversations-open')));
  $('chat-sidebar-close').addEventListener('click', () => { conversations(false); $('chat-menu').focus(); });
  $('chat-attach').addEventListener('click', () => $('chat-reference').click());
  $('chat-reference').addEventListener('change', attachment);
  $('chat-attachment-remove').addEventListener('click', () => { $('chat-reference').value = ''; attachment(); });
  input.addEventListener('input', resize);
  window.addEventListener('resize', resize);
  $('chat-jump').addEventListener('click', jump);
  scroll.addEventListener('scroll', () => { $('chat-jump').hidden = nearBottom(); }, { passive: true });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || document.querySelector('dialog[open]')) return;
    if (!$('project-panel').hidden) project(false);
    else if ($('app').classList.contains('conversations-open')) { conversations(false); $('chat-menu').focus(); }
    $('chat-details').open = false;
  });
  return { project, conversations, resize, attachment, nearBottom, follow, jump };
}
