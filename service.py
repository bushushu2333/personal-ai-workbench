"""Manage only this app's detached local process in the opening user's context."""
import argparse
import fcntl
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
STATE = DATA / 'service.json'
URL = 'http://127.0.0.1:4186'


def health():
    try:
        with urllib.request.urlopen(URL + '/api/health', timeout=1) as response:
            result = json.load(response)
        return result.get('ok') and result.get('app_id') == 'personal-workbench'
    except Exception:
        return False


def owned_process():
    try:
        record = json.loads(STATE.read_text())
        process = psutil.Process(int(record['pid']))
        args = process.cmdline()
        if str(ROOT / 'server.py') in args and abs(process.create_time() - record['created_at']) < 1:
            return process
    except (OSError, ValueError, KeyError, psutil.Error):
        pass
    return None



def start():
    process = owned_process()
    if process and health():
        print('个人工作台已启动：' + URL)
        return
    if process:
        process.terminate()
        try:
            process.wait(timeout=8)
        except psutil.TimeoutExpired:
            raise SystemExit('旧工作台正在结束，请稍后重新打开。')
    with socket.socket() as probe:
        # Match the server's reusable socket: recently closed browser requests
        # may leave TIME_WAIT sockets even though no process is listening.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', 4186))
        except OSError:
            raise SystemExit('4186 端口已被其他进程占用，未改动现有进程。')
    python = ROOT / '.venv' / 'bin' / 'python'
    if not python.exists():
        raise SystemExit('请先双击“打开个人工作台.command”初始化依赖。')
    logs = DATA / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONUNBUFFERED='1')
    env['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin'
    with (logs / 'service.log').open('ab') as out, (logs / 'service-error.log').open('ab') as err:
        child = subprocess.Popen([str(python), str(ROOT / 'server.py'), '--port', '4186'],
                                 cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=err, start_new_session=True)
    record = {'pid': child.pid, 'created_at': psutil.Process(child.pid).create_time(), 'url': URL}
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(record))
    temporary.chmod(0o600)
    os.replace(str(temporary), str(STATE))
    for _ in range(40):
        if health():
            print('个人工作台已启动：' + URL)
            return
        if child.poll() is not None:
            raise SystemExit('服务启动未完成，请查看 data/logs/service-error.log。')
        time.sleep(.5)
    raise SystemExit('服务暂未就绪，请查看 data/logs/service-error.log。')


def stop():
    process = owned_process()
    if process:
        process.terminate()
        try:
            process.wait(timeout=8)
        except psutil.TimeoutExpired:
            raise SystemExit('工作台还在结束，没有强制终止。')
    if STATE.exists():
        STATE.unlink()
    print('已停止个人工作台；数据和其他应用保持不变。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['install', 'start', 'stop', 'status', 'uninstall'])
    action = parser.parse_args().action
    DATA.mkdir(parents=True, exist_ok=True)
    DATA.chmod(0o700)
    with (DATA / 'service.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if action in ('install', 'start'):
            start()
        elif action == 'status':
            print('运行中：' + URL if owned_process() and health() else '未运行')
        else:
            stop()
