"""Read-only delivery of the existing, generated task board.

The original generator and archives remain authoritative. This adapter does not
build, copy or edit them, and never mounts the containing directory wholesale.
"""
import base64
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from workbench.sources import TASK_ROOT


BOARD_FILES = {'index.html', 'style.css', 'common.js', 'assets/avatar.svg', 'assets/hero.svg'}
MAX_HTML_BYTES = 8 * 1024 * 1024
UNAVAILABLE = '任务看板暂时不可读取，请检查本地配置及看板是否已生成。'
TZ = timezone(timedelta(hours=8))


class BoardMarkup(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts = []
        self.handlers = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.handlers.extend(value for key, value in attrs.items() if key.startswith('on') and value)
        if tag == 'script':
            self.current = [attrs, '']

    def handle_data(self, value):
        if self.current is not None:
            self.current[1] += value

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            self.scripts.append(self.current)
            self.current = None


def markup(html):
    parsed = BoardMarkup()
    parsed.feed(html)
    return parsed


def content_policy(html):
    parsed = markup(html)
    executable = [body for attrs, body in parsed.scripts
                  if not attrs.get('src') and attrs.get('type', '').lower()
                  in ('', 'text/javascript', 'application/javascript')]
    def digest(value):
        return "'sha256-" + base64.b64encode(hashlib.sha256(value.encode('utf-8')).digest()).decode('ascii') + "'"
    scripts = ["'self'"] + [digest(body) for body in executable]
    if parsed.handlers:
        scripts += ["'unsafe-hashes'"] + [digest(value) for value in parsed.handlers]
    return ("default-src 'none'; script-src " + ' '.join(dict.fromkeys(scripts)) +
            "; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
            "connect-src 'none'; object-src 'none'; frame-src 'none'; "
            "frame-ancestors 'self'; base-uri 'self'; form-action 'none'")


class TaskBoard:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else TASK_ROOT.parent

    def path(self, relative):
        # Only audited public presentation files. Never expose archives, source
        # generators, credentials, directory listings or arbitrary local paths.
        if relative not in BOARD_FILES and not re.fullmatch(r'tasks/[\w-]+\.html', relative):
            raise HTTPException(404, '没有这个看板页面或资源')
        try:
            root = self.root.resolve(strict=True)
            candidate = (root / relative).resolve(strict=True)
            resolved = candidate.relative_to(root).as_posix()
            if resolved not in BOARD_FILES and not re.fullmatch(r'tasks/[\w-]+\.html', resolved):
                raise ValueError('not a presentation resource')
            if not candidate.is_file():
                raise OSError('not a file')
            return candidate
        except (OSError, ValueError, RuntimeError):
            raise HTTPException(404, '没有这个看板页面或资源')

    def read_html(self, relative='index.html'):
        try:
            path = self.path(relative)
            with path.open('rb') as source:
                raw = source.read(MAX_HTML_BYTES + 1)
            if not raw or len(raw) > MAX_HTML_BYTES:
                raise ValueError('invalid size')
            html = raw.decode('utf-8')
            if not re.search(r'<html\b', html, re.I) or not re.search(r'</html\s*>', html, re.I):
                raise ValueError('incomplete page')
            if relative == 'index.html':
                data = next((body for attrs, body in markup(html).scripts
                             if attrs.get('id') == 'task-data'), None)
                if data is None or not isinstance(json.loads(data), list):
                    raise ValueError('invalid board data')
            return path, raw, html
        except (HTTPException, OSError, UnicodeError, ValueError, StopIteration, RecursionError):
            raise HTTPException(503, UNAVAILABLE)

    def status(self):
        try:
            path, raw, _ = self.read_html()
            modified = path.stat().st_mtime
            newer = any(source.stat().st_mtime > modified
                        for source in (self.root / 'tasks-data').glob('*.md') if source.is_file())
            return {'available': True, 'revision': hashlib.sha256(raw).hexdigest(),
                    'updated_at': datetime.fromtimestamp(modified, TZ).isoformat(timespec='seconds'),
                    'source_newer': newer, 'error': None}
        except (HTTPException, OSError):
            return {'available': False, 'revision': None, 'updated_at': None,
                    'source_newer': False, 'error': UNAVAILABLE}

    def response(self, relative='index.html', embedded=False, task=''):
        if not relative.endswith('.html'):
            return FileResponse(self.path(relative))
        # Distinguish denied paths (404) from an unavailable V2 page (503).
        if relative != 'index.html':
            self.path(relative)
        _, _, html = self.read_html(relative)
        if relative == 'index.html':
            html = re.sub(r'(<span\b[^>]*class="profile-name"[^>]*>)[^<]*(</span>)',
                          r'\1我的空间\2', html)
            html = html.replace('src="assets/avatar.svg"',
                                'src="/static/assets/default-avatar.svg"')
            if embedded:
                html = re.sub(r'<body\b', '<body class="workbench-embedded"', html, count=1)
                html = html.replace('</head>', '<link rel="stylesheet" href="/static/task-board-embed.css?v=20261007-card-copy2"></head>', 1)
            html = html.replace('</body>', '<script src="/static/task-board-embed.js?v=20261007-card-copy2"></script></body>', 1)
        return HTMLResponse(html, headers={'Content-Security-Policy': content_policy(html),
                                           'Cache-Control': 'no-cache'})
