"""Explicit, local-only integration settings. No home-directory discovery."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None):
    path = Path(path or os.environ.get('WORKBENCH_CONFIG', PROJECT_ROOT / 'config.local.json')).expanduser()
    raw = {}
    if path.exists():
        if path.stat().st_size > 256 * 1024:
            raise ValueError('本地配置过大')
        raw = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(raw, dict):
            raise ValueError('本地配置必须为 JSON 对象')
    def local_path(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError('本地路径不能为空')
        value = Path(value).expanduser()
        return str((value if value.is_absolute() else PROJECT_ROOT / value).resolve())
    roots = raw.get('skills_roots', ['examples/skills'])
    if not isinstance(roots, list) or len(roots) > 30:
        raise ValueError('skills_roots 必须为路径列表，最多 30 个')
    enable_ai = raw.get('enable_ai', False)
    if not isinstance(enable_ai, bool):
        raise ValueError('enable_ai 必须为布尔值')
    bridge = raw.get('bridge_url', 'http://127.0.0.1:8791')
    url = urlsplit(bridge)
    if (url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1')
            or url.username or url.password or url.query or url.fragment or url.path not in ('', '/')):
        raise ValueError('AI bridge 必须为本机 HTTP 地址')
    # Accessing .port also rejects malformed ports.
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError('AI bridge 端口无效')
    remotes = raw.get('remote_devices', [])
    if not isinstance(remotes, list) or len(remotes) > 30:
        raise ValueError('remote_devices 必须为列表，最多 30 台')
    devices, hosts, windows, ids = [], {}, [], {'local'}
    for item in remotes:
        if not isinstance(item, dict):
            raise ValueError('远端设备配置格式错误')
        ident, alias, host = (item.get(key, '') for key in ('id', 'ssh_alias', 'host'))
        if not all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', v) for v in (ident, alias, host)):
            raise ValueError('设备 id、SSH 别名及主机必须为安全的标识符或 IPv4/域名')
        if ident in ids or alias in hosts:
            raise ValueError('设备 id 或 SSH 别名重复')
        ids.add(ident)
        enabled = item.get('enabled', False)
        if not isinstance(enabled, bool):
            raise ValueError('设备 enabled 必须为布尔值')
        name, system = item.get('name', ident), item.get('system', 'Linux')
        if not all(isinstance(v, str) and 0 < len(v) <= 100 for v in (name, system)):
            raise ValueError('设备名称或系统格式错误')
        hosts[alias] = host
        if system.lower().startswith('windows'):
            windows.append(alias)
        devices.append({'id': ident, 'name': name, 'system': system, 'alias': alias,
                        'address': host, 'source_kind': 'ssh', 'enabled': enabled,
                        'group': '远端设备', 'environment': '自定义'})
    return {'task_board_root': local_path(raw.get('task_board_root', 'examples/task-board')),
            'skills_roots': [local_path(root) for root in roots], 'enable_ai': enable_ai,
            'bridge_url': bridge.rstrip('/'), 'remote_devices': devices,
            'remote_hosts': hosts, 'windows_aliases': windows}


SETTINGS = load_config()
