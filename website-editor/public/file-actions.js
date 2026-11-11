const $ = id => document.getElementById(id);
export const uploadPath = file => `assets/${file.type.startsWith('image/') ? 'images' : 'files'}/${file.name.replace(/[^A-Za-z0-9._-]/g, '-')}`;
const base64 = file => new Promise((resolve, reject) => {
  const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]);
  reader.onerror = () => reject(new Error('Could not read the selected file.')); reader.readAsDataURL(file);
});

export function createFileActions({ lookup, openFile, saveUpload }) {
  let mode = 'new', checked = null, busy = false;
  function reset() {
    checked = null; $('file-action-replace').checked = false; $('file-action-replace-label').hidden = true;
    $('file-action-error').hidden = true; $('file-action-status').textContent = '';
    $('file-action-submit').textContent = mode === 'new' ? 'Open new source file' : 'Review destination';
  }
  function open(action, path = '') {
    mode = action; $('file-action-form').reset(); reset();
    $('file-action-title').textContent = { new: 'New source file', upload: 'Upload image or file', replace: 'Replace a website file' }[mode];
    $('file-action-upload').hidden = mode === 'new'; $('file-action-upload-input').required = mode !== 'new';
    $('file-action-path').value = path; $('file-action-path').readOnly = mode === 'replace';
    $('file-action-path').placeholder = mode === 'new' ? '_pages/my-page.md' : 'assets/files/my-document.pdf';
    $('file-action-help').textContent = mode === 'new'
      ? 'Choose the exact folder and filename. This opens a blank source editor; save it to propose a new file. Use Add content for a blog post, research entry or talk.'
      : 'Images default to assets/images/; other files default to assets/files/. You can choose another destination. Uploading does not automatically add a link or image to a page.';
    $('file-action-dialog').showModal();
  }
  $('file-action-path').addEventListener('input', reset);
  $('file-action-upload-input').addEventListener('change', () => {
    reset(); const file = $('file-action-upload-input').files[0];
    if (file && mode !== 'replace') $('file-action-path').value = uploadPath(file);
  });
  $('file-action-form').addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return;
    busy = true; $('file-action-submit').disabled = true; $('file-action-error').hidden = true;
    $('file-action-path').disabled = true; $('file-action-upload-input').disabled = true;
    $('file-action-dialog').querySelector('[data-close]').disabled = true;
    try {
      const path = $('file-action-path').value.trim();
      if (mode === 'new') {
        if (await openFile(path, { create: true })) $('file-action-dialog').close();
        return;
      }
      const file = $('file-action-upload-input').files[0];
      if (!file || file.size > 1024 * 1024) throw new Error('Choose a file up to 1 MB.');
      if (!checked) {
        const existing = await lookup(path);
        checked = { path, file, expectedSha: existing.sha ?? null };
        $('file-action-replace').checked = false;
        $('file-action-status').textContent = existing.exists
          ? `This will REPLACE ${path} when published. Links to that path will use the replacement.`
          : `This will CREATE ${path} when published. No existing file will be replaced.`;
        $('file-action-replace-label').hidden = !existing.exists;
        $('file-action-submit').textContent = existing.exists ? 'Save replacement privately' : 'Save upload privately';
        return;
      }
      if (!$('file-action-replace-label').hidden && !$('file-action-replace').checked) {
        $('file-action-error').textContent = 'Confirm replacement of the file shown above, or choose a different destination.';
        $('file-action-error').hidden = false; return;
      }
      if (await saveUpload({ path: checked.path, content: await base64(checked.file), expectedSha: checked.expectedSha, encoding: 'base64', reason: 'Uploaded through the website editor' })) $('file-action-dialog').close();
    } catch (error) { checked = null; $('file-action-submit').textContent = mode === 'new' ? 'Open new source file' : 'Review destination'; $('file-action-error').textContent = error.message; $('file-action-error').hidden = false; }
    finally { busy = false; $('file-action-submit').disabled = false; $('file-action-path').disabled = false; $('file-action-upload-input').disabled = false; $('file-action-dialog').querySelector('[data-close]').disabled = false; }
  });
  $('file-action-dialog').addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  return { open };
}
