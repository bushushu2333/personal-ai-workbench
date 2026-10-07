"""Task handoffs stay portable, current and isolated from original sources."""
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException

from workbench.task_board import TaskBoard
from workbench.task_pages import TaskPages


def write_board(root, tasks):
    data = json.dumps(tasks, ensure_ascii=False).replace('<', '\\u003c')
    source = root / 'index.html'
    source.write_text('<!doctype html><html><head><title>原看板</title></head><body><script id="task-data" type="application/json">' + data + '</script></body></html>', encoding='utf-8')
    return source


def write_source(root, ident='parent', extra=''):
    path = root / 'tasks-data' / (ident + '.md')
    path.write_text('---\nid: ' + ident + '\ntitle: 原任务\nworkspace: /Users/example/work\nrepo: owner/repo\nsecret: never-publish-this\n' + extra + '---\n## 概要\n原档案正文不应整体复制\n', encoding='utf-8')
    return path


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / 'original'
    root.mkdir()
    (root / 'tasks-data').mkdir()
    tasks = [{'id': 'parent', 'title': '父任务', 'priority': 0, 'status': '进行中',
              'brief': '核心任务', 'summary': '完整当前进展', 'next': ['第一步', '第二步'],
              'blocker': '真实卡点', 'milestone': '下周', 'note': '协作说明',
              'decision': '确认实施范围', 'date': '10.08',
              'log': ['旧事件'], 'strategy': ['已确认策略'], 'ignored': 'never-publish-field',
              'subtasks': [{'id': 'child', 'title': '子任务', 'parent': 'parent', 'status': '已完成', 'next': ['保持现状']}]}]
    source = write_source(root)
    write_source(root, 'child')
    board = write_board(root, tasks)
    pages = TaskPages(TaskBoard(root), tmp_path / 'data')
    return root, tasks, source, board, pages


def hashes(root):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file()}


def test_parent_child_complete_snapshot_and_sources_untouched(setup):
    root, tasks, source, board, pages = setup
    before = hashes(root)
    snapshot = pages.snapshot('parent')
    assert snapshot['summary'] == '完整当前进展'
    assert snapshot['next'] == ['第一步', '第二步']
    assert snapshot['strategy'] == ['已确认策略']
    assert snapshot['log'] == ['旧事件']
    assert snapshot['source_path'] == str(source)
    assert snapshot['workspace'] == '/Users/example/work'
    assert snapshot['repo'] == 'owner/repo'
    assert 'ignored' not in snapshot and 'secret' not in snapshot
    child = pages.snapshot('child')
    assert child['parent'] == 'parent' and child['parent_title'] == '父任务'
    result = pages.ensure('parent')
    assert Path(result['path']).read_text(encoding='utf-8') == result['html']
    assert Path(result['path']).parent == pages.data_dir / 'task-pages'
    assert result['url'] == '/tasks/parent'
    assert result['source_revision'] == hashlib.sha256(board.read_bytes()).hexdigest()
    assert '原档案正文不应整体复制' not in result['html']
    assert 'never-publish' not in result['html']
    assert '/tasks/child' in result['html']
    assert '待你确认' in result['html'] and '确认实施范围' in result['html']
    assert '节点 · 10.08' in result['html']
    assert '/tasks/parent' in pages.ensure('child')['html']
    assert hashes(root) == before


def test_html_and_embedded_data_escape_and_redact_credentials(setup):
    root, tasks, source, board, pages = setup
    tasks[0]['title'] = '<img src=x onerror=alert(1)>'
    tasks[0]['summary'] = '<script>evil()</script> token=top-secret-value sk-' + 'x' * 25 + '\n-----BEGIN PRIVATE KEY-----\nSECRETKEYDATA\n-----END PRIVATE KEY-----'
    tasks[0]['next'] = ['![raw](javascript:evil) **unexecuted Markdown**', 'https://x.test/?api_key=private-query-token&safe=yes']
    tasks[0]['strategy'] = ['Bearer private-auth-material']
    write_board(root, tasks)
    result = pages.ensure('parent')
    html = result['html']
    assert '<img src=x' not in html and '&lt;img src=x' in html
    assert '<script>evil()' not in html
    assert '\\u003cimg' in html
    for secret in ('top-secret-value', 'x' * 25, 'SECRETKEYDATA', 'private-query-token', 'private-auth-material'):
        assert secret not in html
    assert '**unexecuted Markdown**' in html
    assert 'javascript:evil' in html  # Text only, never promoted to a link.
    assert 'href="javascript:' not in html


def test_source_must_match_id_and_stay_within_fixed_archive(setup, tmp_path):
    root, tasks, source, board, pages = setup
    source.write_text('---\nid: different\nworkspace: /private/unverified\n---\n', encoding='utf-8')
    snapshot = pages.snapshot('parent')
    assert snapshot['source_path'] is None and snapshot['workspace'] == ''
    source.unlink()
    outside = tmp_path / 'private.md'
    outside.write_text('---\nid: parent\nworkspace: /private/escaped\n---\n', encoding='utf-8')
    source.symlink_to(outside)
    assert pages.snapshot('parent')['source_path'] is None
    source.unlink()
    (root / 'tasks-data').rename(root / 'old-archive')
    (root / 'tasks-data').symlink_to(root / 'old-archive', target_is_directory=True)
    assert pages.snapshot('parent')['source_path'] is None


def test_sensitive_workspace_context_and_arbitrary_yaml_are_not_exposed(setup):
    root, tasks, source, board, pages = setup
    source.write_text('---\nid: parent\nworkspace: /Users/example/.ssh/private-key.pem\nrepo: "https://user:secret@x.test/repo"\ncredentials:\n  token: private-material\n---\n', encoding='utf-8')
    snapshot = pages.snapshot('parent')
    assert snapshot['workspace'] == '[敏感上下文已隐藏]'
    html = pages.ensure('parent')['html']
    assert 'private-key.pem' not in html
    assert 'private-material' not in html
    assert 'user:secret@' not in html


@pytest.mark.parametrize('ident', ['../parent', '/parent', 'parent.html', 'child/../../parent', '', 'a' * 101, '中文', None])
def test_invalid_ids_never_write(setup, ident):
    root, tasks, source, board, pages = setup
    with pytest.raises(KeyError):
        pages.ensure(ident)
    assert not pages.data_dir.exists()


def test_missing_task_and_invalid_board_never_export(setup):
    root, tasks, source, board, pages = setup
    with pytest.raises(KeyError):
        pages.ensure('unknown')
    board.write_text('<html><body>缺失任务数据</body></html>', encoding='utf-8')
    with pytest.raises(HTTPException) as error:
        pages.ensure('parent')
    assert error.value.status_code == 503
    assert not pages.data_dir.exists()


@pytest.mark.parametrize('tasks', [
    [{'id': 'one', 'title': 'A'}, {'id': 'one', 'title': 'B'}],
    [{'id': '../escape', 'title': 'A'}],
    [{'id': 'one', 'title': 'A', 'next': {'bad': 'shape'}}],
    [{'id': 'one', 'title': 'A', 'subtasks': [{'id': 'two', 'title': 'B', 'parent': 'unrelated'}]}],
])
def test_invalid_task_schema_is_unavailable(setup, tasks):
    root, old, source, board, pages = setup
    write_board(root, tasks)
    with pytest.raises(HTTPException) as error:
        pages.ensure('one')
    assert error.value.status_code == 503


def test_export_stable_across_repeated_calls_and_new_service(setup):
    root, tasks, source, board, pages = setup
    first = pages.ensure('parent')
    target = Path(first['path'])
    first_stat = target.stat()
    second = pages.ensure('parent')
    restarted = TaskPages(TaskBoard(root), pages.data_dir).ensure('parent')
    assert first == second == restarted
    assert target.stat().st_mtime_ns == first_stat.st_mtime_ns
    assert target.stat().st_ino == first_stat.st_ino
    target.write_text(first['html'].replace('完整当前进展', '<script>injected()</script>'), encoding='utf-8')
    repaired = pages.ensure('parent')
    assert repaired['html'] == first['html']
    assert target.read_text(encoding='utf-8') == first['html']


def test_source_newer_and_board_revision_refresh_snapshot(setup):
    root, tasks, source, board, pages = setup
    os.utime(board, (1_700_000_000, 1_700_000_000))
    os.utime(source, (1_700_000_001, 1_700_000_001))
    first = pages.ensure('parent')
    assert first['source_newer'] is True
    assert '原始任务档案比生成看板更新' in first['html']
    tasks[0]['summary'] = '另一 AI 刚同步的新进展'
    write_board(root, tasks)
    second = pages.ensure('parent')
    assert first['source_revision'] != second['source_revision']
    assert '另一 AI 刚同步的新进展' in second['html']
    assert '完整当前进展' not in second['html']
    assert second['source_newer'] is False


def test_offline_html_is_self_contained_and_http_copy_fetches_fresh_handoff(setup):
    root, tasks, source, board, pages = setup
    result = pages.ensure('parent')
    html = result['html']
    assert '<style>' in html and '<script>' in html
    assert '<script src=' not in html and '<link rel="stylesheet"' not in html
    assert "location.protocol === 'file:'" in html
    assert 'decodeURIComponent(location.pathname)' in html
    assert 'initial.launch_text.split(initial.path).join(path)' in html
    assert "'/api/tasks/' + encodeURIComponent(initial.id) + '/handoff'" in html
    assert "'X-Workbench': '1'" in html
    assert "navigator.clipboard" in html and "document.execCommand('copy')" in html
    assert 'id="copy-value" readonly' in html
    assert '复制 HTML 路径' in html and '复制启动说明' in html
    assert 'http://127.0.0.1:4186/#tasks' in html
    assert 'http://127.0.0.1:4186/api/tasks/parent/html' in html
    assert 'border-left' not in html
    assert result['path'] in result['launch_text']
    assert str(source) in result['launch_text']


def test_directory_and_target_symlinks_are_rejected(setup, tmp_path):
    root, tasks, source, board, pages = setup
    pages.data_dir.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    directory = pages.data_dir / 'task-pages'
    directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        pages.ensure('parent')
    assert list(outside.iterdir()) == []
    directory.unlink()
    directory.mkdir()
    victim = outside / 'important.html'
    victim.write_text('DO NOT CHANGE', encoding='utf-8')
    (directory / 'parent.html').symlink_to(victim)
    with pytest.raises(ValueError):
        pages.ensure('parent')
    assert victim.read_text() == 'DO NOT CHANGE'
    (directory / 'parent.html').unlink()
    (directory / 'parent.html').mkdir()
    with pytest.raises(ValueError):
        pages.ensure('parent')


def test_concurrent_exports_are_identical_and_leave_no_temporary_files(setup):
    root, tasks, source, board, pages = setup
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(pages.ensure, ['parent'] * 12))
    assert all(result == results[0] for result in results)
    directory = pages.data_dir / 'task-pages'
    assert sorted(path.name for path in directory.iterdir()) == ['parent.html']
    assert (directory / 'parent.html').read_text(encoding='utf-8') == results[0]['html']
