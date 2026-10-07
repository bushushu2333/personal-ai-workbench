import io
import sqlite3
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from server import create_app
from workbench.db import Store


class FakeSources:
    def __init__(self, store, data):
        self.store = store

    def tasks(self):
        return {'items': [{'id': 't1', 'title': '真实任务', 'status': 'progress'}, {'id': 't2', 'title': '任务二', 'status': 'waiting-user'}], 'source_status': 'ok'}

    def discover(self):
        return {'items': [{'id': 'news1', 'title': '资讯线索'}]}

    def refresh(self, kind='all', entity_id=None):
        return {'ok': True, 'results': {kind: {'status': 'cached'}}}

    def devices(self):
        return {'items': [{'id': 'local', 'name': '测试设备'}]}

    def agents(self):
        return {'items': [{'id': 'agent1', 'activities': []}]}


class FakeSkills:
    def __init__(self, store, data):
        pass

    def scan(self):
        return self.list()

    def list(self):
        return {'items': [{'id': 's1', 'name': 'test-skill'}]}


def client(tmp_path):
    app = create_app(tmp_path, background=False, sources_factory=FakeSources, skills_factory=FakeSkills)
    return TestClient(app, base_url='http://127.0.0.1:4186')


def test_atomic_store_updates(tmp_path):
    store = Store(tmp_path / 'db.sqlite3')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: store.update('n', lambda n: n + 1, 0), range(80)))
    assert store.get('n') == 80
    reopened = Store(store.path)
    assert reopened.get('n') == 80


def test_discovery_refresh_routes_dispatch_to_isolated_sources(tmp_path):
    with client(tmp_path) as c:
        for path, kind in [('refresh', 'discover'), ('trending/refresh', 'trending'),
                           ('leaderboards/refresh', 'leaderboards')]:
            response = c.post('/api/discover/' + path, headers={'X-Workbench': '1'}, json={})
            assert response.status_code == 200
            assert response.json()['result']['results'] == {kind: {'status': 'cached'}}
            assert response.json()['discover']['items'][0]['id'] == 'news1'


def test_slow_external_news_does_not_block_other_periodic_refresh(tmp_path):
    news_started, release_news, skills_refreshed = threading.Event(), threading.Event(), threading.Event()

    class SlowNews(FakeSources):
        def refresh(self, kind='all', entity_id=None):
            if kind == 'discover':
                news_started.set()
                release_news.wait(2)
            return super().refresh(kind, entity_id)

    class ObservedSkills(FakeSkills):
        def __init__(self, store, data):
            self.scans = 0

        def scan(self):
            self.scans += 1
            if self.scans > 1:
                skills_refreshed.set()
            return self.list()

    app = create_app(tmp_path, background=True, sources_factory=SlowNews, skills_factory=ObservedSkills)
    try:
        with TestClient(app, base_url='http://127.0.0.1:4186'):
            assert news_started.wait(1)
            assert skills_refreshed.wait(1), 'news timeout must not delay unrelated sources'
            release_news.set()
    finally:
        release_news.set()


def test_relation_accepts_preserved_discovery_alias(tmp_path):
    class AliasedSources(FakeSources):
        def discover(self):
            return {'items': [{'id': 'primary', 'alias_ids': ['legacy'], 'title': '当前项目'}]}

    app = create_app(tmp_path, background=False, sources_factory=AliasedSources, skills_factory=FakeSkills)
    with TestClient(app, base_url='http://127.0.0.1:4186') as c:
        response = c.post('/api/relations', headers={'X-Workbench': '1'}, json={
            'from_type': 'discover', 'from_id': 'legacy', 'to_type': 'task', 'to_id': 't1'})
        assert response.status_code == 200
        relation = response.json()['relations'][0]
        assert relation['from_id'] == 'legacy'
        assert relation['from_snapshot']['title'] == '当前项目'


def test_loopback_host_origin_and_csrf_guards(tmp_path):
    with client(tmp_path) as c:
        assert c.get('/api/bootstrap').status_code == 200
        assert c.get('/api/bootstrap', headers={'Host': 'attacker.example'}).status_code == 403
        assert c.post('/api/daily', json={'mood': '平静'}).status_code == 403
        assert c.post('/api/daily', headers={'X-Workbench': '1', 'Origin': 'https://attacker.example'}, json={'mood': '平静'}).status_code == 403
        response = c.post('/api/daily', headers={'X-Workbench': '1'}, json={'mood': '平静'})
        assert response.status_code == 200
        assert c.get('/api/bootstrap').json()['daily']['mood'] == '平静'
        assert "script-src 'self'" in response.headers['content-security-policy']


def test_focus_constraints_persistence_and_invalid_write_rollback(tmp_path):
    headers = {'X-Workbench': '1'}
    with client(tmp_path) as c:
        result = c.post('/api/daily', headers=headers, json={'focus_task_ids': ['t1', 't2'], 'energy': '平稳'})
        assert result.status_code == 200
        assert c.post('/api/daily', headers=headers, json={'focus_task_ids': ['unknown']}).status_code == 422
        assert c.post('/api/daily', headers=headers, json={'focus_task_ids': ['t1'] * 4}).status_code == 422
    with client(tmp_path) as c:
        assert c.get('/api/bootstrap').json()['daily']['focus_task_ids'] == ['t1', 't2']
        assert c.get('/api/bootstrap').json()['daily']['energy'] == '平稳'


def test_relations_idempotence_and_reversible(tmp_path):
    headers = {'X-Workbench': '1'}
    with client(tmp_path) as c:
        payload = {'from_type': 'task', 'from_id': 't1', 'to_type': 'skill', 'to_id': 's1'}
        for _ in range(2):
            assert c.post('/api/relations', headers=headers, json=payload).status_code == 200
        values = c.get('/api/bootstrap').json()['relations']
        assert len(values) == 1
        assert c.post('/api/relations', headers=headers, json=dict(payload, to_id='missing')).status_code == 422
        assert c.delete('/api/relations/' + values[0]['id'], headers=headers).status_code == 200
        assert c.get('/api/bootstrap').json()['relations'] == []
        for payload in [
            {'from_type': 'discover', 'from_id': 'news1', 'to_type': 'task', 'to_id': 't1'},
            {'from_type': 'discover', 'from_id': 'news1', 'to_type': 'skill', 'to_id': 's1'},
            {'from_type': 'task', 'from_id': 't1', 'to_type': 'agent', 'to_id': 'agent1'},
        ]:
            assert c.post('/api/relations', headers=headers, json=payload).status_code == 200
        assert len(c.get('/api/bootstrap').json()['relations']) == 3


def test_roles_and_consistent_backup(tmp_path):
    headers = {'X-Workbench': '1'}
    with client(tmp_path) as c:
        created = c.post('/api/roles', headers=headers, json={'name': '验收角色', 'tags': '研发,办公'}).json()['role']
        assert created['tags'] == ['研发', '办公']
        assert c.post('/api/roles/' + created['id'] + '/meta', headers=headers, json={'name': ''}).status_code == 422
        current = next(x for x in c.get('/api/bootstrap').json()['roles'] if x['id'] == created['id'])
        assert current['name'] == '验收角色'
        c.post('/api/daily', headers=headers, json={'mood': '专注'})
        response = c.get('/api/backup')
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            zf.extract('workbench.sqlite3', tmp_path / 'restore')
            assert 'RESTORE.txt' in zf.namelist()
        recovered = Store(tmp_path / 'restore' / 'workbench.sqlite3')
        assert any(x['id'] == created['id'] for x in recovered.get('roles'))
