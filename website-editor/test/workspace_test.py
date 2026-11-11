"""Focused bootstrap/export checks, with no network and project-local fixtures."""
import base64
import hashlib
import io
import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

PROJECT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = PROJECT / 'website-editor/runtime/workspace.py'


def blob(value):
    return hashlib.sha1(b'blob ' + str(len(value)).encode() + b'\0' + value).hexdigest()


class WorkspaceChecks(unittest.TestCase):
    def setUp(self):
        self.temp_root = PROJECT / '.codex-tmp'
        self.created_root = not self.temp_root.exists()
        self.parent = self.temp_root / 'editor-efficiency-review'
        self.created_parent = not self.parent.exists()
        self.parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='workspace-export-check-', dir=self.parent)
        self.workspace = pathlib.Path(self.temp.name)
        self.module = types.ModuleType('workspace_under_test')
        exec(compile(SOURCE.read_text(), str(SOURCE), 'exec'), self.module.__dict__)
        for name, value in {'WORKSPACE': self.workspace, 'ROOT': self.workspace / 'project',
                            'INPUT': self.workspace / 'input.json', 'OUTPUT': self.workspace / 'outputs'}.items():
            setattr(self.module, name, value)
        self.data = {'original': {'index.html': '<h1>Old</h1>', 'script.sh': '#!/bin/sh\n'},
                     'working': {'index.html': '<h1>Working</h1>', 'script.sh': '#!/bin/sh\n'},
                     'modes': {'script.sh': '100755'}, 'binaries': {}, 'pending': [],
                     'messages': [], 'assets': [], 'repository': 'owner/site', 'revision': 'revision'}

    def tearDown(self):
        self.temp.cleanup()
        self.assertFalse(self.workspace.exists())
        if self.created_parent:
            self.parent.rmdir()
        if self.created_root:
            self.temp_root.rmdir()

    def prepare(self):
        self.module.INPUT.write_text(json.dumps(self.data))
        self.module.prepare()

    def result(self):
        self.module.export()
        return {item['path']: item for item in json.loads((self.module.OUTPUT / 'review.json').read_text())['edits']}

    def test_working_source_new_page_and_deletion_are_exported_together(self):
        self.prepare()
        self.assertTrue((self.module.ROOT / 'script.sh').stat().st_mode & 0o111)
        (self.module.ROOT / 'new.html').write_text('<h1>New page</h1>')
        (self.module.ROOT / 'script.sh').unlink()
        private = self.module.ROOT / 'context_not_for_upload'
        private.mkdir()
        (private / 'secret.txt').write_text('private')
        changes = self.result()
        self.assertEqual(set(changes), {'index.html', 'new.html', 'script.sh'})
        self.assertEqual(changes['index.html']['content'], '<h1>Working</h1>')
        self.assertIsNone(changes['script.sh']['content'])

    def test_single_source_payload_preserves_pending_edits_and_deletions(self):
        del self.data['working']
        self.data['pending'] = [
            {'path': 'index.html', 'after': '<h1>Private edit</h1>'},
            {'path': 'new.html', 'after': '<h1>New</h1>'},
            {'path': 'script.sh', 'after': None},
        ]
        self.prepare()
        changes = self.result()
        self.assertEqual(changes['index.html']['content'], '<h1>Private edit</h1>')
        self.assertEqual(changes['new.html']['content'], '<h1>New</h1>')
        self.assertIsNone(changes['script.sh']['content'])

    def test_binary_asset_verified_and_pending_replacement_exported(self):
        original, replacement = b'\x89PNG\0old', b'\x89PNG\0new'
        self.data['binaries'] = {'assets/image.png': {'sha': blob(original), 'mode': '100644'}}
        self.data['pending'] = [{'path': 'assets/image.png', 'after': base64.b64encode(replacement).decode(), 'encoding': 'base64'}]
        with patch.object(self.module.urllib.request, 'urlopen', return_value=io.BytesIO(original)):
            self.prepare()
        change = self.result()['assets/image.png']
        self.assertEqual(base64.b64decode(change['content']), replacement)
        self.assertEqual(change['encoding'], 'base64')
        # A former binary can intentionally become text; downloading its old
        # public bytes must not overwrite the pending text replacement.
        self.data['pending'][0].update(after='text replacement', encoding='utf8')
        with patch.object(self.module.urllib.request, 'urlopen', return_value=io.BytesIO(original)):
            self.prepare()
        self.assertEqual(self.result()['assets/image.png']['content'], 'text replacement')

    def test_download_must_match_original_blob(self):
        self.data['binaries'] = {'assets/image.png': {'sha': blob(b'expected'), 'mode': '100644'}}
        with patch.object(self.module.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong')):
            with self.assertRaisesRegex(ValueError, 'did not match'):
                self.prepare()

    def test_symlink_is_rejected_instead_of_exported_as_a_deletion(self):
        self.prepare()
        path = self.module.ROOT / 'index.html'
        path.unlink()
        path.symlink_to(self.module.INPUT)
        with self.assertRaisesRegex(ValueError, 'Symlinks cannot be exported'):
            self.result()

    def test_lazy_assets_preserve_public_files_without_network(self):
        self.data['lazy_binaries'] = True
        self.data['binaries'] = {'assets/image.png': {'sha': blob(b'original'), 'mode': '100644'}}
        with patch.object(self.module.urllib.request, 'urlopen', side_effect=AssertionError('Unexpected download')):
            self.prepare()
        self.assertEqual((self.module.ROOT / 'assets/image.png').read_bytes(), b'')
        self.assertNotIn('assets/image.png', self.result())
        (self.module.ROOT / 'assets/image.png').unlink()
        self.assertIsNone(self.result()['assets/image.png']['content'])

    def test_pending_binary_uploads_keep_actual_bytes_in_lazy_workspace(self):
        value = b'\x89PNG\0replacement'
        self.data['lazy_binaries'] = True
        self.data['binaries'] = {'assets/image.png': {'sha': blob(b'original'), 'mode': '100644'}}
        self.data['pending'] = [{'path': 'assets/image.png', 'after': base64.b64encode(value).decode(), 'encoding': 'base64'}]
        self.prepare()
        self.assertEqual((self.module.ROOT / 'assets/image.png').read_bytes(), value)
        self.assertEqual(base64.b64decode(self.result()['assets/image.png']['content']), value)

    def test_hosted_shell_root_argument_uses_that_workspace(self):
        (self.workspace / 'project-input.json').write_text(json.dumps(self.data))
        scope = {'__name__': '__main__'}
        with patch('sys.argv', ['workspace.py', 'prepare', str(self.workspace)]):
            exec(compile(SOURCE.read_text(), str(SOURCE), 'exec'), scope)
        with patch('sys.argv', ['workspace.py', 'export', str(self.workspace)]):
            exec(compile(SOURCE.read_text(), str(SOURCE), 'exec'), scope)
        self.assertTrue((self.workspace / 'outputs/review.json').is_file())


if __name__ == '__main__':
    unittest.main()
