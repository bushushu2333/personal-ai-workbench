import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import create_app
from workbench.config import load_config
from workbench.sources import SourcesService
from scripts.privacy_check import inspect


def test_no_private_integration_discovery_by_default(tmp_path):
    settings = load_config(tmp_path / 'missing.json')
    assert settings['remote_devices'] == []
    assert settings['remote_hosts'] == {}
    assert settings['enable_ai'] is False
    assert all('/examples/skills' in root for root in settings['skills_roots'])
    # No process inspection, bridge requests or Hermes reads at clean startup.
    with patch.object(SourcesService, '_request', side_effect=AssertionError('unexpected network')), \
            patch.object(SourcesService, '_process_states', side_effect=AssertionError('unexpected AI discovery')), \
            patch.object(SourcesService, '_hermes_snapshot', side_effect=AssertionError('unexpected Hermes read')):
        with TestClient(create_app(tmp_path / 'data', background=False), base_url='http://127.0.0.1:4186') as client:
            bootstrap = client.get('/api/bootstrap')
            assert bootstrap.status_code == 200
            devices = client.get('/api/devices').json()['items']
            assert [item['id'] for item in devices] == ['local']
            assert all(item['enabled'] is False for item in client.get('/api/agents').json()['items'])
            assert client.get('/task-board/').status_code == 200
            page = client.get('/tasks/launch-demo')
            assert page.status_code == 200 and '虚构示例' in page.text
            handoff = client.post('/api/tasks/launch-demo/handoff', headers={'X-Workbench': '1'}, json={}).json()
            assert handoff['path'].startswith(str(tmp_path / 'data' / 'task-pages'))
            skills = client.get('/api/skills').json()['items']
            assert len(skills) == 3 and all(skill['starred'] for skill in skills)


def test_remote_config_is_explicit_and_disabled_until_enabled(tmp_path):
    config = tmp_path / 'config.local.json'
    config.write_text(json.dumps({'remote_devices': [{'id': 'example', 'ssh_alias': 'example-ssh', 'host': '192.0.2.10', 'system': 'Windows'}]}))
    settings = load_config(config)
    assert settings['remote_hosts'] == {'example-ssh': '192.0.2.10'}
    assert settings['remote_devices'][0]['enabled'] is False
    assert settings['windows_aliases'] == ['example-ssh']


@pytest.mark.parametrize('bad', [
    {'bridge_url': 'https://example.org'},
    {'bridge_url': 'http://user:password@127.0.0.1:8791'},
    {'remote_devices': [{'id': 'example', 'ssh_alias': '-oProxyCommand=bad', 'host': '192.0.2.10'}]},
    {'skills_roots': 'not-a-list'},
    {'enable_ai': 'true'},
])
def test_config_rejects_unsafe_or_malformed_integrations(tmp_path, bad):
    config = tmp_path / 'config.local.json'
    config.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        load_config(config)


def test_release_guard_rejects_runtime_files_and_credentials():
    assert inspect('data/task-pages/demo.html', b'<html>private task</html>')
    assert inspect('static/photo.jpg', b'not-a-public-image')
    assert inspect('workbench/config.py', ('credential = "sk-' + 'x' * 40 + '"').encode())
    assert inspect('workbench/unsafe.py', ('host = "' + '10.' * 3 + '10"').encode())
    assert inspect('examples/skills/demo/SKILL.md', b'name: fictional') == []


def test_remote_probe_rejects_unconfigured_alias_before_ssh():
    with patch('workbench.sources.subprocess.run') as run:
        with pytest.raises(ValueError):
            SourcesService._remote_metrics('unconfigured')
        run.assert_not_called()
