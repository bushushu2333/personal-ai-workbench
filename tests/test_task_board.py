"""Serve the existing task board without rebuilding or changing its sources."""

import base64
import hashlib
import json
import os

import pytest
from fastapi.testclient import TestClient

from server import create_app


BASE_URL = 'http://127.0.0.1:4186'
INLINE_SCRIPT = "document.body.dataset.boardReady = 'yes';"


class SourcesStub:
    def __init__(self, store, data_dir):
        pass

    def tasks(self):
        return {'items': [], 'source_status': 'ready'}

    def discover(self):
        return {'items': []}

    def devices(self):
        return {'items': []}

    def agents(self):
        return {'items': []}


class SkillsStub:
    def __init__(self, store, data_dir):
        pass

    def scan(self):
        return self.list()

    def list(self):
        return {'items': []}


def board_html(title='原有任务', items=None):
    if items is None:
        items = [{'id': 'existing-task', 'title': title, 'state': 'progress'}]
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">'
        '<title>我的任务看板</title></head><body>'
        '<header class="site-header"><span class="profile-name">Example User</span>'
        '<img class="avatar" src="assets/avatar.svg"></header>'
        f'<main id="main"><h1>{title}</h1><input id="search" type="search">'
        '<div id="task-list"></div></main><dialog id="detail-dialog"></dialog>'
        f'<script id="task-data" type="application/json">{json.dumps(items, ensure_ascii=False)}</script>'
        f'<script>{INLINE_SCRIPT}</script></body></html>'
    )


@pytest.fixture
def board_root(tmp_path):
    root = tmp_path / 'source-board'
    root.mkdir()
    (root / 'index.html').write_text(board_html(), encoding='utf-8')
    (root / 'tasks-data').mkdir()
    return root


def client_for(tmp_path, board_root):
    app = create_app(tmp_path / 'app-data', background=False,
                     sources_factory=SourcesStub, skills_factory=SkillsStub,
                     task_board_root=board_root)
    return TestClient(app, base_url=BASE_URL)


def source_hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file() and not path.is_symlink()}


def script_directive(response):
    policy = response.headers['content-security-policy']
    return next(piece.strip() for piece in policy.split(';')
                if piece.strip().startswith('script-src '))


def test_original_view_and_embed_adapter_do_not_write_sources(tmp_path, board_root):
    (board_root / 'tasks-data' / 'existing-task.md').write_text(
        '---\nid: existing-task\n---\n原有任务档案\n', encoding='utf-8')
    before = source_hashes(board_root)
    with client_for(tmp_path, board_root) as client:
        status = client.get('/api/task-board').json()
        assert status['available'] is True and status['revision'] and status['updated_at']
        original = client.get('/task-board/')
        assert original.status_code == 200
        assert 'text/html' in original.headers['content-type']
        assert '<h1>原有任务</h1>' in original.text
        assert '我的空间' in original.text and 'Example User' not in original.text
        assert '/static/assets/default-avatar.svg' in original.text
        assert '/static/task-board-embed.js' in original.text
        embedded = client.get('/task-board/index.html?embedded=1&task=existing-task')
        assert embedded.status_code == 200
        assert '/static/task-board-embed.css' in embedded.text
        assert '/static/task-board-embed.js' in embedded.text
        assert '<h1>原有任务</h1>' in embedded.text
    assert source_hashes(board_root) == before


def test_standalone_task_page_copy_and_download_use_own_file_only(tmp_path, board_root):
    source = board_root / 'tasks-data' / 'existing-task.md'
    source.write_text('---\nid: existing-task\ntitle: 原有任务\n---\n## 概要\n原档案。\n', encoding='utf-8')
    before = source_hashes(board_root)
    with client_for(tmp_path, board_root) as client:
        page = client.get('/tasks/existing-task')
        assert page.status_code == 200
        assert '复制 HTML 路径' in page.text and '复制启动说明' in page.text
        assert "'unsafe-inline'" not in script_directive(page)
        assert "'sha256-" in script_directive(page)
        assert "connect-src 'self'" in page.headers['content-security-policy']
        assert client.post('/api/tasks/existing-task/handoff', json={}).status_code == 403
        handoff = client.post('/api/tasks/existing-task/handoff', json={}, headers={'X-Workbench': '1'})
        assert handoff.status_code == 200
        info = handoff.json()
        from pathlib import Path
        exported = Path(info['path'])
        assert exported == tmp_path / 'app-data' / 'task-pages' / 'existing-task.html'
        assert info['path'] in info['launch_text']
        assert info['source_path'] == str(source)
        assert 'html' not in info
        assert exported.read_text(encoding='utf-8') == page.text
        download = client.get('/api/tasks/existing-task/html')
        assert download.text == page.text
        assert 'attachment' in download.headers['content-disposition']
        assert client.get('/tasks/no-such-task').status_code == 404
        assert client.post('/api/tasks/no-such-task/handoff', json={}, headers={'X-Workbench': '1'}).status_code == 404
        assert not (tmp_path / 'app-data' / 'task-pages' / 'no-such-task.html').exists()
    assert source_hashes(board_root) == before


def test_new_source_revision_is_served_without_restart_or_import(tmp_path, board_root):
    with client_for(tmp_path, board_root) as client:
        first = client.get('/api/task-board').json()
        assert '原有任务' in client.get('/task-board/').text
        source = board_root / 'index.html'
        source.write_text(board_html('另一会话刚更新的任务'), encoding='utf-8')
        second = client.get('/api/task-board').json()
        assert second['available'] is True
        assert second['revision'] != first['revision']
        assert '另一会话刚更新的任务' in client.get('/task-board/index.html').text
        cache_control = client.get('/task-board/').headers['cache-control']
        assert 'no-cache' in cache_control or 'no-store' in cache_control


@pytest.mark.parametrize('broken', [None, '', '<html><body>缺少任务数据</body></html>',
                                  '<html><body><script id="task-data" type="application/json">{}</script></body></html>',
                                  '<html><body><script id="task-data" type="application/json">not-json</script></body></html>'])
def test_missing_empty_or_invalid_board_is_unavailable_not_an_empty_board(tmp_path, board_root, broken):
    source = board_root / 'index.html'
    if broken is None:
        source.unlink()
    else:
        source.write_text(broken, encoding='utf-8')
    before = source_hashes(board_root)
    with client_for(tmp_path, board_root) as client:
        status = client.get('/api/task-board').json()
        assert status['available'] is False and status['error']
        assert client.get('/task-board/').status_code == 503
    assert source_hashes(board_root) == before


def test_a_valid_board_with_no_tasks_remains_available(tmp_path, board_root):
    (board_root / 'index.html').write_text(board_html('暂无活跃任务', items=[]), encoding='utf-8')
    with client_for(tmp_path, board_root) as client:
        assert client.get('/api/task-board').json()['available'] is True
        response = client.get('/task-board/')
        assert response.status_code == 200 and '暂无活跃任务' in response.text


def test_status_distinguishes_archives_newer_than_generated_view(tmp_path, board_root):
    source = board_root / 'index.html'
    archive = board_root / 'tasks-data' / 'existing-task.md'
    archive.write_text('归档更新由原看板负责', encoding='utf-8')
    stamp = source.stat().st_mtime
    os.utime(archive, (stamp - 60, stamp - 60))
    with client_for(tmp_path, board_root) as client:
        assert client.get('/api/task-board').json()['source_newer'] is False
        os.utime(archive, (stamp + 60, stamp + 60))
        status = client.get('/api/task-board').json()
        assert status['available'] is True and status['source_newer'] is True
        assert source.read_text(encoding='utf-8') == board_html()


def test_only_board_inline_script_is_hash_allowed_parent_policy_stays_strict(tmp_path, board_root):
    expected = "'sha256-" + base64.b64encode(hashlib.sha256(INLINE_SCRIPT.encode('utf-8')).digest()).decode('ascii') + "'"
    with client_for(tmp_path, board_root) as client:
        for path in ('/task-board/', '/task-board/index.html?embedded=1'):
            directive = script_directive(client.get(path))
            assert expected in directive
            assert "'unsafe-inline'" not in directive
        assert script_directive(client.get('/')) == "script-src 'self'"
        assert script_directive(client.get('/api/task-board')) == "script-src 'self'"


def test_resource_allowlist_keeps_archive_and_arbitrary_files_private(tmp_path, board_root):
    allowed = [
        'assets/hero.svg',
        'assets/avatar.svg',
        'tasks/sample-task.html', 'style.css', 'common.js',
    ]
    denied = ['build.py', 'template.html', 'private.json', '.private.html',
              'tasks-data/private.md', 'tasks/private.md', 'tasks/.private.html',
              'tasks/nested/private.html', 'assets/private.png']
    for name in allowed + denied:
        path = board_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(board_html() if name.endswith('.html') else 'fixture-resource', encoding='utf-8')
    with client_for(tmp_path, board_root) as client:
        for name in allowed:
            assert client.get('/task-board/' + name).status_code == 200, name
        for name in denied:
            assert client.get('/task-board/' + name).status_code == 404, name
        for path in ('/task-board/%2e%2e%2foutside.html',
                     '/task-board/tasks/%2e%2e%2fbuild.py',
                     '/task-board/tasks/%2e%2e%2f%2e%2e%2foutside.html'):
            assert client.get(path).status_code == 404, path


def test_allowlisted_symlinks_cannot_escape_board_root(tmp_path, board_root):
    outside = tmp_path / 'outside.html'
    outside.write_text(board_html('不应泄漏的外部内容'), encoding='utf-8')
    tasks = board_root / 'tasks'
    tasks.mkdir()
    (tasks / 'escaped.html').symlink_to(outside)
    assets = board_root / 'assets'
    assets.mkdir(parents=True)
    (assets / 'avatar.svg').symlink_to(outside)
    private = board_root / 'tasks-data' / 'private.md'
    private.write_text('根内任务档案也不能经资源别名公开', encoding='utf-8')
    (assets / 'hero.svg').symlink_to(private)
    with client_for(tmp_path, board_root) as client:
        assert client.get('/task-board/tasks/escaped.html').status_code == 404
        assert client.get('/task-board/assets/avatar.svg').status_code == 404
        assert client.get('/task-board/assets/hero.svg').status_code == 404
        source = board_root / 'index.html'
        source.unlink()
        source.symlink_to(outside)
        assert client.get('/api/task-board').json()['available'] is False
        assert client.get('/task-board/').status_code == 503
