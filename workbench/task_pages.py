"""Portable, read-only task handoffs derived from the existing generated board.

Only application-owned HTML snapshots are written. The generator, original
board and Markdown archives remain authoritative and are never modified.
"""
import hashlib
import json
import os
import re
import stat
import threading
import uuid
from datetime import datetime
from html import escape
from pathlib import Path

import yaml
from fastapi import HTTPException

from workbench.sources import safe_text
from workbench.task_board import TZ, UNAVAILABLE, markup


TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
WORKBENCH_URL = 'http://127.0.0.1:4186'
MAX_SOURCE_BYTES = 256 * 1024
MAX_EXPORT_BYTES = 4 * 1024 * 1024
FORMAT_VERSION = 1
TEXT_FIELDS = ('title', 'subtitle', 'status', 'brief', 'summary', 'blocker', 'milestone', 'note', 'decision', 'date')
LIST_FIELDS = ('next', 'log', 'strategy')
PRIVATE_KEY = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?(?:-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|\Z)', re.S)
QUERY_SECRET = re.compile(r'(?i)([?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|token)=)[^&#\s]+')
SENSITIVE_CONTEXT = re.compile(r'(?i)(?:密钥|密码|凭据|private[_ -]?key|credentials?|secrets?|api[_ -]?key|/\.ssh/|\.(?:pem|p12|pfx)(?:\b|/))')


def _now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def _stamp(timestamp):
    return datetime.fromtimestamp(timestamp, TZ).isoformat(timespec='seconds')


def _text(value):
    if value is None:
        return ''
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError('任务展示字段格式错误')
    value = str(value)
    if len(value) > 128 * 1024:
        raise ValueError('任务展示字段过大')
    value = PRIVATE_KEY.sub('[私钥已隐藏]', value)
    value = QUERY_SECRET.sub(r'\1[已隐藏]', value)
    return safe_text(value, len(value))


def _json(value):
    # The JSON is data only; angle brackets must not terminate its script tag.
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


STYLE = '''
:root{color-scheme:light;--paper:#f8f6f1;--ink:#38283e;--muted:#7a7180;--line:#e7e1e9;--grape:#62436b;--soft:#f0eaf2}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.8 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}a{color:var(--grape);text-underline-offset:4px}button,textarea{font:inherit}button,a.button{cursor:pointer;border:1px solid var(--line);border-radius:999px;padding:10px 20px;background:white;color:var(--ink);text-decoration:none;line-height:1.4;font-size:14px;display:inline-flex;align-items:center;justify-content:center}button.primary{background:var(--grape);border-color:var(--grape);color:white}button:hover,a.button:hover{filter:brightness(.97)}button:disabled{opacity:.6;cursor:wait}button:focus-visible,a:focus-visible,textarea:focus-visible{outline:3px solid #bba1c3;outline-offset:4px}
.shell{max-width:1050px;margin:auto;padding:28px 36px 64px}.topbar{display:flex;align-items:center;justify-content:space-between;gap:18px;color:var(--muted);font-size:13px;margin-bottom:35px}.topbar a{text-decoration:none}.hero{margin-bottom:24px}.eyebrow{color:var(--muted);font-size:13px;letter-spacing:.05em}h1{font-size:clamp(27px,4.8vw,40px);line-height:1.4;margin:12px 0 10px;letter-spacing:-.025em}h2{font-size:19px;line-height:1.5;margin:0 0 18px}h3{font-size:15px;margin:0 0 7px}.subtitle,.brief{color:var(--muted);margin:0 0 15px}.meta,.actions,.links{display:flex;align-items:center;flex-wrap:wrap;gap:10px}.meta{margin:18px 0 22px}.pill{border:1px solid var(--line);border-radius:999px;background:#fff;padding:3px 12px;font-size:12px}.pill.soft{background:var(--soft);color:var(--grape);border-color:transparent}.actions{gap:12px}.download{font-size:13px;margin-left:5px}.section{background:#fff;border:1px solid var(--line);border-radius:18px;padding:26px 30px;margin:18px 0}.prose{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}ol,ul{padding-left:23px;margin:0}li{padding-left:4px;white-space:pre-wrap;overflow-wrap:anywhere}li+li{margin-top:12px}.next li::marker{color:var(--grape);font-weight:600}.children{display:grid;gap:14px}.child{border:1px solid var(--line);border-radius:12px;padding:16px 20px}.child p{margin:5px 0 0;color:var(--muted);font-size:13px}.subtle{color:var(--muted);font-size:13px}.notice{background:var(--soft);color:var(--grape);border-radius:12px;padding:14px 18px;margin-top:20px}.notice p{margin:0}.handoff{margin-top:28px}.handoff details+details{margin-top:18px}summary{cursor:pointer;font-weight:600;margin-bottom:14px}.field{margin:15px 0}.field strong{display:block;font-size:13px;margin-bottom:5px}.path,pre{font:12px/1.8 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere;white-space:pre-wrap;word-break:break-word;background:var(--paper);border-radius:10px;padding:13px 16px;margin:0}.launch{font-family:inherit;font-size:14px}.foot{margin-top:25px;font-size:12px;color:var(--muted)}#copy-fallback{margin-top:20px;background:var(--soft);padding:18px;border-radius:12px}#copy-fallback[hidden]{display:none}#copy-fallback p{margin:0 0 10px}textarea{display:block;width:100%;min-height:110px;border:1px solid #bba1c3;border-radius:9px;padding:12px;resize:vertical;font-size:13px;background:white;color:var(--ink)}#toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--ink);color:#fff;border-radius:999px;padding:11px 24px;font-size:13px;box-shadow:0 7px 30px #38283e1a;max-width:calc(100% - 35px);text-align:center}#toast:empty{display:none}@media(max-width:600px){.shell{padding:20px 18px 40px}.topbar{margin-bottom:25px}.section{padding:21px 20px;border-radius:15px}.actions{gap:9px}.actions button{padding:10px 15px}.download{margin:4px 8px}.meta{gap:7px}.path,pre{padding:11px 12px}.child{padding:14px 15px}}@media print{body{background:white}.shell{max-width:none;padding:0}.actions,.topbar,#toast,#copy-fallback{display:none!important}.section{break-inside:avoid}details> :not(summary){display:block!important}a{color:inherit}}
'''


COPY_SCRIPT = '''
(() => {
  'use strict';
  const initial = JSON.parse(document.getElementById('task-handoff-data').textContent);
  const toast = document.getElementById('toast');
  const fallback = document.getElementById('copy-fallback');
  const field = document.getElementById('copy-value');
  let timer;
  function inform(message) {
    toast.textContent = message;
    clearTimeout(timer);
    timer = setTimeout(() => { toast.textContent = ''; }, 4500);
  }
  async function copy(value) {
    if (navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(value); fallback.hidden = true; return true; } catch (_) {}
    }
    fallback.hidden = false;
    field.value = value;
    field.focus(); field.select(); field.setSelectionRange(0, value.length);
    try {
      if (document.execCommand('copy')) { fallback.hidden = true; return true; }
    } catch (_) {}
    return false;
  }
  async function latest() {
    if (location.protocol === 'file:') {
      const path = decodeURIComponent(location.pathname);
      if (!path || !path.startsWith('/')) throw new Error('无法读取当前 HTML 的绝对路径');
      return {...initial, path, launch_text: initial.launch_text.split(initial.path).join(path)};
    }
    if (location.protocol !== 'http:' && location.protocol !== 'https:') throw new Error('请从工作台或本地 HTML 文件打开');
    const response = await fetch('/api/tasks/' + encodeURIComponent(initial.id) + '/handoff', {
      method: 'POST', headers: {'X-Workbench': '1', 'Content-Type': 'application/json'}, body: '{}'
    });
    if (!response.ok) throw new Error('暂时无法取得最新任务，请刷新后重试');
    const result = await response.json();
    if (result.id !== initial.id || typeof result.path !== 'string' || !result.path.startsWith('/') || typeof result.launch_text !== 'string') throw new Error('任务交接信息不完整');
    return result;
  }
  document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const data = await latest();
      const value = button.dataset.copy === 'path' ? data.path : data.launch_text;
      document.getElementById('html-path').textContent = data.path;
      document.getElementById('launch-text').textContent = data.launch_text;
      const done = await copy(value);
      inform(done ? (button.dataset.copy === 'path' ? '已复制 HTML 绝对路径' : '已复制任务启动说明') : '自动复制未成功，可在下方选中并复制');
    } catch (error) { inform(error.message || '复制未完成，请重试'); }
    finally { button.disabled = false; }
  }));
})();
'''


class TaskPages:
    def __init__(self, board, data_dir):
        self.board = board
        self.data_dir = Path(data_dir).expanduser().absolute()
        self._data_root = self.data_dir.resolve()
        self._lock = threading.RLock()

    @staticmethod
    def _id(task_id):
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            raise KeyError(task_id)
        return task_id

    def _tasks(self, html):
        try:
            records = [body for attrs, body in markup(html).scripts if attrs.get('id') == 'task-data']
            if len(records) != 1:
                raise ValueError('任务数据不唯一')
            items = json.loads(records[0])
            if not isinstance(items, list) or len(items) > 1000:
                raise ValueError('任务数据格式错误')
            lookup = {}

            def collect(raw, parent=None, depth=0):
                if not isinstance(raw, dict) or depth > 8 or len(lookup) >= 1000:
                    raise ValueError('任务层级格式错误')
                ident = self._id(raw.get('id'))
                if ident in lookup:
                    raise ValueError('任务标识重复')
                title = _text(raw.get('title'))
                if not title.strip():
                    raise ValueError('任务缺少标题')
                item = {'id': ident, **{key: _text(raw.get(key)) for key in TEXT_FIELDS}}
                priority = raw.get('priority')
                item['priority'] = priority if type(priority) is int and priority in (0, 1, 2) else None
                declared_parent = raw.get('parent')
                if declared_parent is not None:
                    declared_parent = self._id(declared_parent)
                if parent is not None and declared_parent not in (None, parent):
                    raise ValueError('子任务父级不一致')
                item['parent'] = parent or declared_parent
                for key in LIST_FIELDS:
                    entries = raw.get(key) or []
                    if not isinstance(entries, list) or len(entries) > 500:
                        raise ValueError('任务列表字段格式错误')
                    item[key] = [_text(entry) for entry in entries]
                lookup[ident] = item
                children = raw.get('subtasks') or []
                if not isinstance(children, list) or len(children) > 500:
                    raise ValueError('子任务格式错误')
                item['subtasks'] = [collect(child, ident, depth + 1) for child in children]
                return item

            for raw in items:
                collect(raw)
            return lookup
        except (KeyError, TypeError, ValueError, RecursionError, OverflowError):
            raise HTTPException(503, UNAVAILABLE)

    def _source(self, task_id, board_modified):
        empty = {'source_path': None, 'source_updated_at': None, 'source_newer': False,
                 'workspace': '', 'repo': '', 'source_error': '原始任务档案暂未核验，请先确认原看板来源。'}
        try:
            root = self.board.root.resolve(strict=True)
            archive = root / 'tasks-data'
            candidate = archive / (task_id + '.md')
            if archive.is_symlink() or candidate.is_symlink():
                return empty
            resolved = candidate.resolve(strict=True)
            if resolved.parent != archive or not candidate.is_file():
                return empty
            with candidate.open('rb') as stream:
                raw = stream.read(MAX_SOURCE_BYTES + 1)
            if len(raw) > MAX_SOURCE_BYTES:
                return empty
            text = raw.decode('utf-8')
            match = re.match(r'\A\ufeff?---\s*\n(.*?)\n---\s*(?:\n|$)', text, re.S)
            meta = yaml.safe_load(match.group(1)) if match else None
            if not isinstance(meta, dict) or str(meta.get('id', '')) != task_id:
                return empty
            modified = candidate.stat().st_mtime
            result = {'source_path': str(resolved), 'source_updated_at': _stamp(modified),
                      'source_newer': modified > board_modified, 'source_error': None}
            for key in ('workspace', 'repo'):
                value = meta.get(key)
                if value is not None and not isinstance(value, str):
                    result[key] = ''
                    continue
                result[key] = '[敏感上下文已隐藏]' if SENSITIVE_CONTEXT.search(value or '') else _text(value)
            return result
        except (OSError, UnicodeError, ValueError, yaml.YAMLError, RecursionError):
            return empty

    def snapshot(self, task_id):
        task_id = self._id(task_id)
        path, raw, html = self.board.read_html()
        tasks = self._tasks(html)
        if task_id not in tasks:
            raise KeyError(task_id)
        try:
            modified = path.stat().st_mtime
        except OSError:
            raise HTTPException(503, UNAVAILABLE)
        task = dict(tasks[task_id])
        parent = tasks.get(task.get('parent'))
        task.update({'source_revision': hashlib.sha256(raw).hexdigest(),
                     'board_updated_at': _stamp(modified),
                     'parent_title': parent['title'] if parent else task.get('parent') or ''})
        task.update(self._source(task_id, modified))
        return task

    def _open_directory(self):
        if self.data_dir.is_symlink() or self.data_dir.resolve() != self._data_root:
            raise ValueError('任务快照目录不可使用软链接')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        base = os.open(str(self.data_dir), flags)
        try:
            try:
                os.mkdir('task-pages', 0o700, dir_fd=base)
            except FileExistsError:
                pass
            try:
                directory = os.open('task-pages', flags, dir_fd=base)
            except OSError:
                raise ValueError('任务快照目录不可使用软链接或普通文件')
            if (self.data_dir / 'task-pages').resolve() != self._data_root / 'task-pages':
                os.close(directory)
                raise ValueError('任务快照目录超出应用数据范围')
            return directory
        finally:
            os.close(base)

    @staticmethod
    def _check_target(directory, filename):
        try:
            mode = os.stat(filename, dir_fd=directory, follow_symlinks=False).st_mode
        except FileNotFoundError:
            return
        if not stat.S_ISREG(mode):
            raise ValueError('任务 HTML 目标必须为普通文件，不能使用软链接')

    def _existing(self, directory, filename):
        self._check_target(directory, filename)
        try:
            descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        except FileNotFoundError:
            return '', {}
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError('任务 HTML 目标不是普通文件')
            with os.fdopen(descriptor, 'rb', closefd=False) as stream:
                raw = stream.read(MAX_EXPORT_BYTES + 1)
            if len(raw) > MAX_EXPORT_BYTES:
                return '', {}
            html = raw.decode('utf-8')
            data = next((body for attrs, body in markup(html).scripts
                         if attrs.get('id') == 'task-handoff-data'), '')
            metadata = json.loads(data)
            return html, metadata if isinstance(metadata, dict) else {}
        except (UnicodeError, ValueError, RecursionError):
            return '', {}
        finally:
            os.close(descriptor)

    @staticmethod
    def _atomic_write(directory, filename, html):
        temporary = '.' + filename + '-' + uuid.uuid4().hex + '.tmp'
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8', closefd=False) as stream:
                stream.write(html)
                stream.flush()
                os.fsync(descriptor)
            TaskPages._check_target(directory, filename)
            os.replace(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass

    def ensure(self, task_id):
        with self._lock:
            task = self.snapshot(task_id)
            path = str(self._data_root / 'task-pages' / (task['id'] + '.html'))
            fingerprint = hashlib.sha256(json.dumps({'format': FORMAT_VERSION, 'task': task, 'path': path}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
            directory = self._open_directory()
            try:
                filename = task['id'] + '.html'
                previous, metadata = self._existing(directory, filename)
                exported = metadata.get('exported_at') if metadata.get('fingerprint') == fingerprint else None
                try:
                    if not isinstance(exported, str) or len(exported) > 40 or not datetime.fromisoformat(exported).tzinfo:
                        exported = None
                except ValueError:
                    exported = None
                exported = exported or _now()
                launch = self._launch(task, path)
                result = {'id': task['id'], 'path': path, 'url': '/tasks/' + task['id'],
                          'source_revision': task['source_revision'], 'source_path': task['source_path'],
                          'source_newer': task['source_newer'], 'exported_at': exported, 'launch_text': launch}
                html = self._render(task, {**result, 'fingerprint': fingerprint})
                if len(html.encode('utf-8')) > MAX_EXPORT_BYTES:
                    raise ValueError('任务交接 HTML 过大')
                if html != previous:
                    self._atomic_write(directory, filename, html)
                result['html'] = html
                return result
            finally:
                os.close(directory)

    @staticmethod
    def _launch(task, path):
        parts = ['请先读取这份本地任务交接 HTML，再核对原始任务档案的最新进度，从“接下来”继续推进：',
                 path, '', '任务：' + task['title'], '任务标识：' + task['id']]
        if task['source_path']:
            parts.append('原始任务档案：' + task['source_path'])
        else:
            parts.append('原始任务档案暂未核验；请先确认原看板来源。')
        if task['source_newer']:
            parts.append('原始任务档案比生成看板更新，务必先读取原档案，以最新内容为准。')
        if task['workspace']:
            parts.append('工作区：' + task['workspace'])
        if task['repo']:
            parts.append('仓库：' + task['repo'])
        parts.append('按本次明确任务与当前有效约定执行；历史事件日志仅供背景，不代表新的执行授权。')
        parts.append('这份 HTML 是交接快照；任务状态仍以原始任务档案为准。')
        return '\n'.join(parts)

    @staticmethod
    def _render(task, data):
        def text(value):
            return escape(str(value or ''), quote=True)

        def section(title, body, extra=''):
            return '<section class="section ' + extra + '"><h2>' + title + '</h2>' + body + '</section>' if body else ''

        def prose(value):
            return '<p class="prose">' + text(value) + '</p>' if value else ''

        def listing(values, ordered=False):
            tag = 'ol' if ordered else 'ul'
            return '<' + tag + (' class="next"' if ordered else '') + '>' + ''.join('<li>' + text(value) + '</li>' for value in values) + '</' + tag + '>' if values else ''

        parent = ''
        if task['parent']:
            parent = '<p class="subtle">父任务：<a href="' + WORKBENCH_URL + '/tasks/' + task['parent'] + '">' + text(task['parent_title']) + '</a></p>'
        children = ''.join('<article class="child"><h3><a href="' + WORKBENCH_URL + '/tasks/' + child['id'] + '">' + text(child['title']) + '</a></h3><span class="subtle">' + text(child['status']) + '</span>' + ('<p>' + text(child['brief']) + '</p>' if child['brief'] else '') + '</article>' for child in task['subtasks'])
        status = '<span class="pill soft">' + text(task['status']) + '</span>' if task['status'] else ''
        priority = '<span class="pill">P' + str(task['priority']) + '</span>' if task['priority'] is not None else ''
        date = '<span class="pill">节点 · ' + text(task['date']) + '</span>' if task['date'] else ''
        notice = ''
        if task['source_newer']:
            notice = '<div class="notice"><p>原始任务档案比生成看板更新。接续任务时请先读取原档案，以最新进度为准。</p></div>'
        elif task['source_error']:
            notice = '<div class="notice"><p>' + text(task['source_error']) + '</p></div>'
        source = task['source_path'] or '尚未核验'
        context = ''.join('<div class="field"><strong>' + label + '</strong><p class="path">' + text(task[key]) + '</p></div>' for key, label in (('workspace', '工作区'), ('repo', '仓库')) if task[key])
        history = ''
        if task['strategy']:
            history += '<details open><summary>策略与决策</summary>' + listing(task['strategy']) + '</details>'
        if task['log']:
            history += '<details open><summary>事件日志</summary>' + listing(task['log']) + '</details>'
        url = WORKBENCH_URL + '/api/tasks/' + task['id'] + '/html'
        return ('<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<meta name="referrer" content="no-referrer"><title>' + text(task['title']) + ' · 任务交接</title><style>' + STYLE + '</style></head><body>'
                '<main class="shell"><nav class="topbar" aria-label="任务导航"><span>个人工作台 · 任务交接</span><a href="' + WORKBENCH_URL + '/#tasks">返回任务看板 ↗</a></nav>'
                '<header class="hero"><span class="eyebrow">任务详情</span><h1>' + text(task['title']) + '</h1>'
                + ('<p class="subtitle">' + text(task['subtitle']) + '</p>' if task['subtitle'] else '')
                + ('<p class="brief">' + text(task['brief']) + '</p>' if task['brief'] else '') + parent
                + '<div class="meta">' + priority + status + date + '</div><div class="actions"><button class="primary" data-copy="path">复制 HTML 路径</button><button data-copy="launch">复制启动说明</button><a class="download" href="' + url + '" download>下载 HTML</a></div>' + notice
                + '<div id="copy-fallback" hidden><p>请选中下面的内容，按 ⌘C 或 Ctrl+C 复制。</p><textarea id="copy-value" readonly aria-label="待复制的任务信息"></textarea></div></header>'
                + section('当前进展', prose(task['summary']))
                + section('接下来', listing(task['next'], True))
                + section('待你确认', prose(task['decision']))
                + section('当前卡点', prose(task['blocker']))
                + section('时间节点', prose(task['milestone']))
                + section('协作备注', prose(task['note']))
                + section('子任务', '<div class="children">' + children + '</div>' if children else '')
                + section('任务记录', history)
                + '<section class="section handoff"><h2>交接给另一个 AI</h2><p class="subtle">在本机使用时复制 HTML 路径；发送文件给同事时，可下载这份 HTML。</p><div class="field"><strong>本地 HTML 绝对路径</strong><p class="path" id="html-path">' + text(data['path']) + '</p></div>'
                '<div class="field"><strong>启动说明</strong><pre class="launch" id="launch-text">' + text(data['launch_text']) + '</pre></div>'
                '<div class="field"><strong>原始任务档案</strong><p class="path">' + text(source) + '</p></div>' + context
                + '<p class="subtle">看板更新：' + text(task['board_updated_at']) + ('<br>档案更新：' + text(task['source_updated_at']) if task['source_updated_at'] else '') + '<br>交接页生成：' + text(data['exported_at']) + '</p>'
                '<details><summary>来源修订</summary><p class="path">' + text(task['source_revision']) + '</p></details></section>'
                '<p class="foot">这是一份任务交接快照。原始任务档案持续维护任务进度。</p></main><div id="toast" role="status" aria-live="polite"></div>'
                '<script id="task-handoff-data" type="application/json">' + _json(data) + '</script><script>' + COPY_SCRIPT + '</script></body></html>')
