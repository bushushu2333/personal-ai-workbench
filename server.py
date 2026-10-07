"""Personal workbench. Run: python server.py (local machine only)."""
import argparse
import io
import logging
import os
import re
import tempfile
import threading
import uuid
import zipfile
from contextlib import asynccontextmanager, nullcontext
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, quote

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from workbench.db import Store
from workbench.task_board import TaskBoard, content_policy
from workbench.task_pages import TaskPages

ROOT = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=8))
VERSION = '1.0.0'
APP_ID = 'personal-workbench'
LOG = logging.getLogger('workbench')


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def today():
    return datetime.now(TZ).date().isoformat()


def clean_text(value, limit=2000):
    if value is None:
        return ''
    return str(value).strip()[:limit]


def create_app(data_dir=None, background=True, sources_factory=None, skills_factory=None, task_board_root=None):
    data = Path(data_dir or os.environ.get('WORKBENCH_DATA_DIR', str(ROOT / 'data'))).resolve()
    data.mkdir(parents=True, exist_ok=True)
    os.chmod(str(data), 0o700)
    store = Store(data / 'workbench.sqlite3')
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(app):
        if skills_factory is None:
            from workbench.skills import SkillsService
            app.state.skills = SkillsService(store, data)
        else:
            app.state.skills = skills_factory(store, data)
        if sources_factory is None:
            from workbench.sources import SourcesService
            app.state.sources = SourcesService(store, data, start_background=background)
        else:
            app.state.sources = sources_factory(store, data)
        app.state.skills.scan()
        if skills_factory is None and not store.get('examples.curated', False):
            example_names = {
                'workbench-maintenance': ('工作台维护', '核心维护'),
                'image-brief': ('AI 生图需求整理', 'AI 生图'),
                'presentation-outline': ('PPT 大纲规划', 'PPT 演示'),
            }
            example_root = (ROOT / 'examples' / 'skills').resolve()
            for skill in app.state.skills.list().get('items', []):
                if Path(skill['real_path']).parent == example_root and skill['name'] in example_names:
                    label, category = example_names[skill['name']]
                    app.state.skills.meta(skill['id'], {'starred': True, 'display_name': label,
                        'category': category, 'pinned': skill['name'] == 'workbench-maintenance'})
            store.set('examples.curated', True)
        if store.get('roles') is None:
            store.set('roles', [
                {'id': 'planner', 'name': '规划助手', 'description': '规划、架构分析与交付', 'tags': ['研发', '规划'], 'archived': False},
                {'id': 'assistant', 'name': '日常助手', 'description': '日常事务与综合助理', 'tags': ['办公', '助理'], 'archived': False},
                {'id': 'builder', 'name': '工程助手', 'description': '工程实现与问题攻坚', 'tags': ['研发'], 'archived': False},
            ])
        if store.get('relations') is None:
            store.set('relations', [])
        if store.get('settings') is None:
            store.set('settings', {'interests': ['AI', '教育', '开源', '产品']})

        periods = {'tasks': 30, 'agents': 10, 'devices': 45, 'discover': 1800,
                   'trending': 1800, 'leaderboards': 900, 'skills': 600}

        def worker(kind):
            while not stop.is_set():
                try:
                    if kind == 'skills':
                        app.state.skills.scan()
                    else:
                        app.state.sources.refresh(kind)
                except Exception:
                    LOG.exception('Background refresh failed: %s', kind)
                stop.wait(periods[kind])

        threads = []
        if background:
            for kind in periods:
                thread = threading.Thread(target=worker, args=(kind,), daemon=True,
                                          name='workbench-refresh-' + kind)
                threads.append(thread)
                thread.start()
        yield
        stop.set()
        close = getattr(app.state.sources, 'close', None)
        if close:
            close()
        for thread in threads:
            thread.join(timeout=.5)

    app = FastAPI(title='个人工作台', version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.data_dir = data
    app.state.task_board = TaskBoard(task_board_root)
    app.state.task_pages = TaskPages(app.state.task_board, data)

    @app.middleware('http')
    async def local_guard(request: Request, call_next):
        host = request.headers.get('host', '').split(':')[0].lower()
        if host not in ('127.0.0.1', 'localhost', '[::1]'):
            return JSONResponse({'detail': '此工作台只允许本机访问'}, status_code=403)
        origin = request.headers.get('origin')
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme not in ('http', 'https') or parsed.netloc != request.headers.get('host'):
                return JSONResponse({'detail': '请求来源不匹配，请从本地工作台打开'}, status_code=403)
        if request.url.path.startswith('/api/') and request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            if request.headers.get('x-workbench') != '1':
                return JSONResponse({'detail': '请通过工作台页面完成此操作'}, status_code=403)
            try:
                if int(request.headers.get('content-length', '0')) > 8 * 1024 * 1024:
                    return JSONResponse({'detail': '提交内容过大，请将单次资料限制在 8MB 内'}, status_code=413)
            except ValueError:
                return JSONResponse({'detail': '无效的请求长度'}, status_code=400)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if not (request.url.path.startswith(('/task-board/', '/tasks/')) and response.headers.get('Content-Security-Policy')):
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'self'; base-uri 'self'"
        response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else 'no-cache'
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': clean_text(exc, 500) or '输入内容有误'}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({'detail': '没有找到这条记录，请刷新后重试'}, status_code=404)

    def daily(date=None):
        d = date or today()
        return store.get('daily:' + d, {'date': d, 'mood': '', 'energy': '', 'focus_task_ids': []})

    def bundle():
        sources = app.state.sources
        tasks = sources.tasks()
        return {
            'daily': daily(), 'tasks': tasks, 'skills': app.state.skills.list(),
            'discover': sources.discover(), 'devices': sources.devices(), 'agents': sources.agents(),
            'roles': store.get('roles', []), 'relations': store.get('relations', []),
            'settings': store.get('settings', {'interests': ['AI', '教育', '开源', '产品']}),
            'health': {'version': VERSION, 'server_time': now(), 'local_only': True, 'task_source_status': tasks.get('source_status', 'unknown')},
        }

    @app.get('/api/health')
    def health():
        return {'ok': True, 'app_id': APP_ID, 'version': VERSION, 'time': now(), 'local_only': True}

    @app.get('/api/bootstrap')
    @app.get('/api/home')
    def bootstrap():
        return bundle()

    @app.get('/api/daily')
    def get_daily(date: str = None):
        if date and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
            raise ValueError('日期格式应为 YYYY-MM-DD')
        return daily(date)

    @app.post('/api/daily')
    def save_daily(payload: dict):
        d = clean_text(payload.get('date') or today(), 10)
        try:
            datetime.strptime(d, '%Y-%m-%d')
        except ValueError:
            raise ValueError('日期格式应为 YYYY-MM-DD')
        focus = payload.get('focus_task_ids')
        if focus is not None:
            if not isinstance(focus, list) or len(focus) > 3:
                raise ValueError('今日重点最多选择 3 个任务')
            focus = list(dict.fromkeys(clean_text(x, 200) for x in focus))
            known = {str(x['id']) for x in app.state.sources.tasks().get('items', [])}
            old = set(daily(d).get('focus_task_ids', []))
            if any(x not in known and x not in old for x in focus):
                raise ValueError('所选任务不存在，请重新选择')
        def change(existing):
            value = existing or {'date': d, 'mood': '', 'energy': '', 'focus_task_ids': []}
            for key in ('mood', 'energy'):
                if key in payload:
                    value[key] = clean_text(payload[key], 32)
            if focus is not None:
                value['focus_task_ids'] = focus
                current = {str(x['id']): x for x in app.state.sources.tasks().get('items', [])}
                old_snapshots = value.get('focus_snapshots', {})
                value['focus_snapshots'] = {key: {'id': key, 'title': clean_text(current[key].get('title'), 300)} if key in current else old_snapshots.get(key, {'id': key, 'title': '来源暂不可用的任务'}) for key in focus}
            value['updated_at'] = now()
            return value
        value = store.update('daily:' + d, change)
        return {'ok': True, 'daily': value}

    @app.get('/api/tasks')
    def tasks():
        return app.state.sources.tasks()

    @app.get('/api/task-board')
    def task_board_status():
        return app.state.task_board.status()

    @app.get('/task-board/')
    def task_board_index(embedded: bool = False, task: str = ''):
        return app.state.task_board.response(embedded=embedded, task=task)

    @app.get('/task-board/{relative:path}')
    def task_board_resource(relative: str, embedded: bool = False, task: str = ''):
        return app.state.task_board.response(relative, embedded=embedded, task=task)

    @app.get('/tasks/{task_id}')
    def independent_task(task_id: str):
        page = app.state.task_pages.ensure(task_id)
        policy = content_policy(page['html']).replace("connect-src 'none'", "connect-src 'self'")
        return HTMLResponse(page['html'], headers={'Content-Security-Policy': policy})

    @app.post('/api/tasks/{task_id}/handoff')
    def task_handoff(task_id: str):
        page = app.state.task_pages.ensure(task_id)
        return {'ok': True, **{key: value for key, value in page.items() if key != 'html'}}

    @app.get('/api/tasks/{task_id}/html')
    def download_task_html(task_id: str):
        page = app.state.task_pages.ensure(task_id)
        return Response(page['html'], media_type='text/html', headers={
            'Content-Disposition': 'attachment; filename="' + page['id'] + '.html"'})

    @app.get('/api/tasks/{task_id}')
    def task_detail(task_id: str):
        for item in app.state.sources.tasks().get('items', []):
            if str(item['id']) == task_id:
                return item
        raise KeyError(task_id)

    def check_reference(kind, entity_id):
        kind = {'instance': 'agent', 'runtime': 'agent', 'agent-role': 'role'}.get(kind, kind)
        groups = {
            'task': lambda: app.state.sources.tasks().get('items', []),
            'skill': lambda: app.state.skills.list().get('items', []),
            'device': lambda: app.state.sources.devices().get('items', []),
            'agent': lambda: app.state.sources.agents().get('items', []),
            'role': lambda: store.get('roles', []),
            'discover': lambda: app.state.sources.discover().get('items', []),
            'activity': lambda: [a for x in app.state.sources.agents().get('items', []) for a in x.get('activities', [])],
        }
        if kind not in groups:
            raise ValueError('不支持的关联类型')
        matched = next((x for x in groups[kind]() if str(x.get('id')) == entity_id or
                        (kind == 'discover' and entity_id in x.get('alias_ids', []))), None)
        if matched is None:
            raise ValueError('关联对象不存在，请刷新后重新选择')
        snapshot = {key: clean_text(matched.get(key), 500) for key in ('id', 'title', 'name', 'platform', 'state', 'last_activity_at') if matched.get(key) is not None}
        snapshot['captured_at'] = now()
        return kind, snapshot

    @app.post('/api/relations')
    def relation(payload: dict):
        item = {k: clean_text(payload.get(k), 200) for k in ('from_type', 'from_id', 'to_type', 'to_id')}
        if not all(item.values()):
            raise ValueError('请完整选择关联对象')
        item['from_type'], item['from_snapshot'] = check_reference(item['from_type'], item['from_id'])
        item['to_type'], item['to_snapshot'] = check_reference(item['to_type'], item['to_id'])
        preserve = getattr(app.state.sources, 'preserve_discovery', None)
        if preserve:
            for side in ('from', 'to'):
                if item[side + '_type'] == 'discover':
                    preserve(item[side + '_id'])
        item['id'] = uuid.uuid4().hex[:16]
        item['created_at'] = now()
        def change(items):
            items = items or []
            if not any(all(x.get(k) == item[k] for k in ('from_type', 'from_id', 'to_type', 'to_id')) for x in items):
                items.append(item)
            return items
        items = store.update('relations', change, [])
        return {'ok': True, 'relations': items}

    @app.delete('/api/relations/{relation_id}')
    def unrelate(relation_id: str):
        items = store.update('relations', lambda xs: [x for x in (xs or []) if x['id'] != relation_id], [])
        return {'ok': True, 'relations': items}

    @app.get('/api/skills')
    def skills():
        return app.state.skills.list()

    @app.post('/api/skills/scan')
    def scan_skills():
        result = app.state.skills.scan()
        return {'ok': True, 'skills': result}

    @app.post('/api/skills/drafts')
    def draft(payload: dict):
        result = app.state.skills.create_draft(payload)
        return {'ok': True, 'skill': result, 'id': result['id']}

    @app.put('/api/skills/drafts/{skill_id}')
    def edit_draft(skill_id: str, payload: dict):
        result = app.state.skills.edit_draft(skill_id, payload)
        return {'ok': True, 'skill': result, 'id': result['id']}

    @app.get('/api/skills/{skill_id}')
    def skill_detail(skill_id: str):
        return app.state.skills.detail(skill_id)

    @app.post('/api/skills/{skill_id}/meta')
    def skill_meta(skill_id: str, payload: dict):
        return {'ok': True, 'skill': app.state.skills.meta(skill_id, payload), 'id': skill_id}

    @app.post('/api/skills/{skill_id}/archive')
    def skill_archive(skill_id: str, payload: dict = None):
        return {'ok': True, 'skill': app.state.skills.meta(skill_id, {'archived': True})}

    @app.post('/api/skills/{skill_id}/check')
    def skill_check(skill_id: str):
        return {'ok': True, 'skill': app.state.skills.check(skill_id), 'id': skill_id}

    @app.post('/api/skills/{skill_id}/validate')
    def skill_validate(skill_id: str, payload: dict):
        return {'ok': True, 'skill': app.state.skills.validate(skill_id, payload), 'id': skill_id}

    @app.post('/api/skills/{skill_id}/register')
    def skill_register(skill_id: str):
        return {'ok': True, 'skill': app.state.skills.register(skill_id), 'id': skill_id}

    @app.get('/api/skills/{skill_id}/prompt')
    def skill_prompt(skill_id: str, task_id: str = None, target: str = None):
        task = None
        if task_id:
            task = next((x for x in app.state.sources.tasks().get('items', []) if str(x['id']) == task_id), None)
        return {'prompt': app.state.skills.prompt(skill_id, task=task, target=target)}

    @app.get('/api/skills/{skill_id}/export')
    def skill_export(skill_id: str):
        filename, content = app.state.skills.export(skill_id)
        return Response(content=content, media_type='application/zip', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename)})

    @app.get('/api/skills/{skill_id}/copy-target')
    def skill_copy_target(skill_id: str):
        return app.state.skills.copy_target(skill_id)

    @app.get('/api/discover')
    def discover():
        return app.state.sources.discover()

    @app.post('/api/discover/refresh')
    def refresh_discover():
        return {'ok': True, 'result': app.state.sources.refresh('discover'), 'discover': app.state.sources.discover()}

    @app.post('/api/discover/trending/refresh')
    def refresh_trending():
        return {'ok': True, 'result': app.state.sources.refresh('trending'), 'discover': app.state.sources.discover()}

    @app.post('/api/discover/leaderboards/refresh')
    def refresh_leaderboards():
        return {'ok': True, 'result': app.state.sources.refresh('leaderboards'), 'discover': app.state.sources.discover()}

    @app.post('/api/discover/projects')
    def add_project(payload: dict):
        return {'ok': True, 'project': app.state.sources.add_project(payload)}

    @app.post('/api/discover/{item_id}/meta')
    def discover_meta(item_id: str, payload: dict):
        return {'ok': True, 'item': app.state.sources.discover_meta(item_id, payload)}

    @app.post('/api/settings')
    def settings(payload: dict):
        interests = payload.get('interests', [])
        if isinstance(interests, str):
            interests = re.split(r'[,，\n]', interests)
        if not isinstance(interests, list):
            raise ValueError('兴趣应为一个列表')
        value = store.update('settings', lambda x: dict(x or {}, interests=list(dict.fromkeys(clean_text(s, 40) for s in interests if clean_text(s)))[:20]), {})
        return {'ok': True, 'settings': value}

    @app.get('/api/devices')
    def devices():
        return app.state.sources.devices()

    @app.post('/api/devices')
    def add_device(payload: dict):
        return {'ok': True, 'device': app.state.sources.device_save(payload)}

    @app.post('/api/devices/{device_id}/meta')
    def device_meta(device_id: str, payload: dict):
        return {'ok': True, 'device': app.state.sources.device_save(payload, id=device_id)}

    @app.post('/api/devices/{device_id}/refresh')
    def refresh_device(device_id: str):
        return {'ok': True, 'result': app.state.sources.refresh('devices', entity_id=device_id)}

    @app.get('/api/agents')
    def agents():
        return app.state.sources.agents()

    @app.post('/api/agents/{agent_id}/meta')
    def agent_meta(agent_id: str, payload: dict):
        if 'role_ids' in payload:
            if not isinstance(payload['role_ids'], list):
                raise ValueError('请选择角色列表')
            known = {x['id'] for x in store.get('roles', [])}
            if any(x not in known for x in payload['role_ids']):
                raise ValueError('所选角色不存在')
        return {'ok': True, 'agent': app.state.sources.agent_meta(agent_id, payload)}

    @app.post('/api/roles')
    def add_role(payload: dict):
        name = clean_text(payload.get('name'), 80)
        if not name:
            raise ValueError('请填写角色名称')
        tags = payload.get('tags', [])
        if isinstance(tags, str):
            tags = re.split(r'[,，]', tags)
        if not isinstance(tags, list):
            raise ValueError('标签格式有误')
        item = {'id': 'role-' + uuid.uuid4().hex[:12], 'name': name, 'description': clean_text(payload.get('description')), 'tags': [clean_text(x, 40) for x in tags][:20], 'archived': False}
        store.update('roles', lambda items: (items or []) + [item], [])
        return {'ok': True, 'role': item, 'id': item['id']}

    @app.post('/api/roles/{role_id}/meta')
    def role_meta(role_id: str, payload: dict):
        if not any(x['id'] == role_id for x in store.get('roles', [])):
            raise KeyError(role_id)
        def change(items):
            for item in items:
                if item['id'] == role_id:
                    for key in ('name', 'description'):
                        if key in payload:
                            item[key] = clean_text(payload[key], 80 if key == 'name' else 2000)
                    if not item.get('name'):
                        raise ValueError('请填写角色名称')
                    if 'archived' in payload:
                        item['archived'] = bool(payload['archived'])
                    if 'tags' in payload:
                        tags = payload['tags']
                        if isinstance(tags, str):
                            tags = re.split(r'[,，]', tags)
                        if not isinstance(tags, list):
                            raise ValueError('标签格式有误')
                        item['tags'] = [clean_text(x, 40) for x in tags][:20]
            return items
        items = store.update('roles', change, [])
        return {'ok': True, 'role': next(x for x in items if x['id'] == role_id)}

    @app.post('/api/refresh')
    def refresh(payload: dict = None):
        payload = payload or {}
        kind = payload.get('kind', 'all')
        if kind == 'skills':
            result = app.state.skills.scan()
        elif kind in ('all', 'tasks', 'discover', 'devices', 'agents'):
            result = app.state.sources.refresh(kind, entity_id=payload.get('id'))
        else:
            raise ValueError('不支持的刷新类型')
        return {'ok': True, 'result': result}

    def build_backup():
        buf = io.BytesIO()
        with tempfile.TemporaryDirectory(prefix='workbench-backup-') as temporary:
            db = Path(temporary) / 'workbench.sqlite3'
            store.backup(db)
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(str(db), 'workbench.sqlite3')
                for child in data.iterdir():
                    if not child.is_dir() or child.is_symlink() or child.name in ('logs', 'backups', 'exports', 'tmp'):
                        continue
                    for f in sorted(child.rglob('*')):
                        if f.is_file() and not f.is_symlink():
                            zf.write(str(f), str(f.relative_to(data)))
                zf.writestr('RESTORE.txt', '先停止个人工作台。将 workbench.sqlite3 和技能文件目录恢复到 data/；删除旧的 -wal/-shm 文件后重新启动。不要覆盖其他应用的任务或技能目录。\n')
        return Response(buf.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="workbench-backup-' + today() + '.zip"'})

    @app.get('/api/backup')
    def backup():
        guard = getattr(app.state.skills, 'backup_guard', None)
        with guard() if guard else nullcontext():
            return build_backup()

    static = ROOT / 'static'
    app.mount('/static', StaticFiles(directory=str(static)), name='static')

    @app.get('/')
    def index():
        return FileResponse(str(static / 'index.html'))

    return app


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=4186)
    parser.add_argument('--data-dir', default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    uvicorn.run(create_app(args.data_dir), host='127.0.0.1', port=args.port, access_log=False)
