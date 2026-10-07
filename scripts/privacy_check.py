"""Inspect the exact Git index, without reading or printing local runtime data.

This conservative guard supplements human review; it is not a DLP guarantee.
"""
import ipaddress
import hashlib
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
ROOT_FILES = {
    'server.py', 'service.py', 'requirements.txt', 'requirements-dev.txt',
    '打开个人工作台.command', 'config.example.json', '.gitignore',
    'README.md', 'LICENSE', 'PRIVACY.md', 'SECURITY.md', 'CONTRIBUTING.md',
}
FOLDERS = {'workbench', 'static', 'examples', 'docs', 'tests', 'scripts', '.github'}
EXTENSIONS = {'.py', '.js', '.css', '.html', '.md', '.svg', '.yml', '.yaml'}
# Visually reviewed screenshots from an isolated synthetic-data environment.
# Replacing any image requires a new content review and digest.
REVIEWED_IMAGES = {
    "docs/screenshots/home.jpg": "0666fc4453bdce77f082fb6e2a992fd1b5ecf4274a1aadb38be4829a42ecfaab",
    "docs/screenshots/tasks.jpg": "a3f0a0fe01f38e40969db6d220e63ccbaec57a0f972cc2bf4e8dd2029b92e462",
    "docs/screenshots/skills.jpg": "39390fb9521bf6e6223cfb31d93b0de4d6ca287be13c490aec546366b3de460f",
    "docs/screenshots/devices.jpg": "4f534dbc9e37617737945262dd7c73964e64fbe770d21634a016f84e49381433"
}
PATTERNS = [
    ('credential-shaped value', re.compile(r'\b(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})\b')),
    ('private key block', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----\s*\n[A-Za-z0-9+/=]{20,}')),
    ('personal macOS path', re.compile(r'/Users/(?!example(?:/|\b)|person(?:/|\b))[A-Za-z0-9_.-]+/')),
    ('mounted personal volume', re.compile(r'/Volumes/[A-Za-z0-9_\u4e00-\u9fff-]+/')),
]
DOCUMENTATION_NETWORKS = [ipaddress.ip_network(net) for net in ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24')]


def inspect(name, data, mode='100644'):
    problems = []
    path = PurePosixPath(name)
    if mode not in ('100644', '100755'):
        problems.append('symlink or submodule is not allowed')
    if name not in REVIEWED_IMAGES and name not in ROOT_FILES and (path.parts[0] not in FOLDERS or path.suffix not in EXTENSIONS):
        problems.append('file is outside the public source allowlist')
    if any(part in ('data', 'private', 'artifacts', 'release', '__pycache__', '.venv') for part in path.parts) or name.endswith('.local.json'):
        problems.append('private/runtime path')
    if name in REVIEWED_IMAGES:
        if (len(data) > 2 * 1024 * 1024 or not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9')
                or hashlib.sha256(data).hexdigest() != REVIEWED_IMAGES[name]):
            problems.append('screenshot differs from the reviewed image')
        if b'Exif\x00' in data or b'http://ns.adobe.com/xap' in data:
            problems.append('screenshot contains image metadata')
        return problems
    if len(data) > 2 * 1024 * 1024 or b'\x00' in data:
        problems.append('binary or oversized content')
        return problems
    try:
        text = data.decode('utf-8')
    except UnicodeError:
        return problems + ['non-UTF-8 content']
    for label, pattern in PATTERNS:
        if pattern.search(text):
            problems.append(label)
    for match in re.finditer(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', text):
        try:
            address = ipaddress.ip_address(match.group())
        except ValueError:
            continue
        if not address.is_loopback and not any(address in net for net in DOCUMENTATION_NETWORKS):
            problems.append('non-example IP address requires review')
            break
    return problems


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    try:
        entries = git('ls-files', '--stage', '-z').split(b'\x00')
    except subprocess.CalledProcessError:
        print('Initialize Git and stage public files before running this check.')
        return 1
    count, failed = 0, False
    for entry in entries:
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        mode, oid, stage = metadata.decode().split()
        name = name.decode('utf-8')
        data = git('cat-file', 'blob', oid)
        problems = inspect(name, data, mode)
        if stage != '0':
            problems.append('unresolved index conflict')
        count += 1
        if problems:
            failed = True
            print(name + ': ' + '; '.join(problems))
    if not count:
        print('No staged/tracked source files found. Stage the public source first.')
        return 1
    print('%d indexed files checked; %s.' % (count, 'review required' if failed else 'privacy guard passed'))
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
