"""Materialize the private working source and export a reviewable result.

Runs only in the remote agent sandbox, never against the user's computer.
"""
import json
import base64
import hashlib
import pathlib
import sys
import urllib.parse
import urllib.request

WORKSPACE = pathlib.Path('/workspace')
ROOT = WORKSPACE / 'project'
INPUT = WORKSPACE / 'project-input.json'
OUTPUT = WORKSPACE / 'outputs'
SKIP = {'.git', '.codex', '.codex-tmp', '.vercel', 'node_modules', 'vendor',
        '_site', '.jekyll-cache', '.bundle', 'context_not_for_upload', '__pycache__'}


def allowed(path):
    parts = pathlib.PurePosixPath(path).parts
    return parts and not path.startswith('/') and all(
        p not in ('.', '..') and p.lower() not in SKIP for p in parts
    ) and not (parts[-1].startswith('.env') and parts[-1] != '.env.example')


def prepare():
    data = json.loads(INPUT.read_text())
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, text in data['working'].items():
        if not allowed(name):
            raise ValueError('Invalid workspace input path')
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if data.get('modes', {}).get(name) == '100755':
            path.chmod(0o755)
    total = 0
    for name, entry in data.get('binaries', {}).items():
        if not allowed(name):
            raise ValueError('Invalid binary path')
        if data.get('lazy_binaries'):
            # Keep large public assets represented without blocking ordinary
            # chat on network access. Export preserves untouched placeholders.
            path = ROOT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'')
            continue
        url = 'https://raw.githubusercontent.com/' + data['repository'] + '/' + data['revision'] + '/' + urllib.parse.quote(name)
        with urllib.request.urlopen(url, timeout=30) as response:
            value = response.read(50 * 1024 * 1024 + 1)
        total += len(value)
        if len(value) > 50 * 1024 * 1024 or total > 150 * 1024 * 1024:
            raise ValueError('Public asset download exceeded the workspace budget')
        sha = hashlib.sha1(b'blob ' + str(len(value)).encode() + b'\0' + value).hexdigest()
        if sha != entry['sha']:
            raise ValueError('Public asset content did not match the repository revision')
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        if entry.get('mode') == '100755':
            path.chmod(0o755)
    for change in data.get('pending', []):
        if not allowed(change['path']):
            raise ValueError('Invalid pending path')
        path = ROOT / change['path']
        if change['after'] is None:
            path.unlink(missing_ok=True)
        elif change.get('encoding') == 'base64':
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(change['after'], validate=True))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change['after'])
    (WORKSPACE / 'conversation.json').write_text(json.dumps(data['messages']))
    (WORKSPACE / 'public-assets.json').write_text(json.dumps(data['assets']))


def export():
    """Compare all source to the public baseline, including pending edits."""
    data = json.loads(INPUT.read_text())
    current = {}
    for path in ROOT.rglob('*'):
        name = path.relative_to(ROOT).as_posix()
        if not allowed(name):
            continue
        if path.is_symlink():
            raise ValueError('Symlinks cannot be exported: ' + name)
        if not path.is_file():
            continue
        value = path.read_bytes()
        binary = data.get('binaries', {}).get(name)
        sha = hashlib.sha1(b'blob ' + str(len(value)).encode() + b'\0' + value).hexdigest()
        pending = next((change for change in data.get('pending', []) if change['path'] == name), None)
        placeholder = binary and data.get('lazy_binaries') and not value and pending is None
        if binary and (sha == binary['sha'] or placeholder):
            current[name] = {'unchanged': True}
            continue
        try:
            text = value.decode('utf8')
            if '\x00' in text:
                raise UnicodeDecodeError('utf8', value, 0, 1, 'binary file')
        except UnicodeDecodeError:
            if len(value) > 1024 * 1024:
                raise ValueError('A changed binary file exceeds the 1 MB editor upload limit: ' + name)
            current[name] = {'content': base64.b64encode(value).decode(), 'encoding': 'base64'}
            continue
        if len(value) > 500000:
            raise ValueError('A changed source file exceeds the editor limit: ' + name)
        current[name] = {'content': text, 'encoding': 'utf8'}
    changes = []
    for name in sorted(set(data['original']) | set(data.get('binaries', {})) | set(current)):
        before, after = data['original'].get(name), current.get(name)
        if after and after.get('unchanged'):
            continue
        if after and after['encoding'] == 'utf8' and before == after['content']:
            continue
        changes.append({'path': name, 'content': after['content'] if after else None, 'encoding': after['encoding'] if after else 'utf8', 'reason': 'Updated in the online workspace'})
    OUTPUT.mkdir(exist_ok=True)
    message = WORKSPACE / 'result-message.txt'
    (OUTPUT / 'review.json').write_text(json.dumps({
        'message': message.read_text() if message.exists() else 'Workspace changes are ready for review.',
        'edits': changes,
    }))


if __name__ == '__main__':
    if len(sys.argv) > 2:
        WORKSPACE = pathlib.Path(sys.argv[2])
        ROOT, INPUT, OUTPUT = WORKSPACE / 'project', WORKSPACE / 'project-input.json', WORKSPACE / 'outputs'
    {'prepare': prepare, 'export': export}[sys.argv[1]]()
