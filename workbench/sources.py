"""Read-only adapters for the personal workbench.

The application owns metadata and snapshots; task archives, AI applications and
remote machines remain the source of truth. No adapter exposes arbitrary files,
commands, or a write-capable endpoint of another application.
"""
import base64
import copy
import gzip
import hashlib
import json
import math
from workbench.config import SETTINGS
import platform
import re
import shutil
import stat
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo

import psutil
import yaml


SHANGHAI = ZoneInfo("Asia/Shanghai")
TASK_ROOT = Path(SETTINGS["task_board_root"]) / "tasks-data"
AIHOT_URL = "https://aihot.news/api/v1/items?mode=selected&window=7d&limit=50"
TRENDING_URL = "https://github.com/trending?since=daily"
LEADERBOARD_URLS = {
    "overall": "https://aihot.news/leaderboard",
    **{kind: "https://aihot.news/leaderboard/category/" + kind
       for kind in ("coding", "reasoning", "professional", "knowledge")},
}
BRIDGE_URL = SETTINGS["bridge_url"]
MAX_RESPONSE = 2 * 1024 * 1024
AGENT_TTL = 45
DEVICE_TTL = 150

DEVICE_SEEDS = [
    {"id": "local", "name": "本机", "system": platform.system(), "group": "日常设备", "environment": "本机", "source_kind": "local", "alias": None, "enabled": True},
] + SETTINGS["remote_devices"]
# No remote machines are configured in the public distribution.
# A user must explicitly supply exact alias/host pairs in ignored local config.
REMOTE_HOSTS = SETTINGS["remote_hosts"]
REMOTE_CONNECTIONS = {}
WINDOWS_ALIASES = frozenset(SETTINGS["windows_aliases"])
AGENT_SEEDS = [
    {"id": "codex-local", "name": "Codex", "platform": "codex", "device_id": "local"},
    {"id": "zcode-local", "name": "ZCode", "platform": "zcode", "device_id": "local"},
    {"id": "kimi-local", "name": "Kimi", "platform": "kimi", "device_id": "local"},
    {"id": "hermes-local", "name": "Hermes Gateway", "platform": "hermes", "device_id": "local"},
]
METRIC_KEYS = ("cpu_percent", "memory_percent", "disk_percent", "memory_used_gb", "memory_total_gb", "disk_free_gb", "disk_total_gb")

# Fixed, stdlib-only probes. -B disables bytecode writes on the remote machine.
UNIX_PROBE = r'''import json,os,platform,re,shutil,subprocess,time
m={k:None for k in ['cpu_percent','memory_percent','disk_percent','memory_used_gb','memory_total_gb','disk_free_gb','disk_total_gb']}
d=shutil.disk_usage('/');m.update(disk_percent=round((d.total-d.free)*100/d.total,1),disk_free_gb=round(d.free/1073741824,2),disk_total_gb=round(d.total/1073741824,2))
if platform.system()=='Linux':
 mem={x.split(':')[0]:int(x.split()[1])*1024 for x in open('/proc/meminfo') if ':' in x and len(x.split())>1 and x.split()[1].isdigit()}
 total=mem.get('MemTotal');available=mem.get('MemAvailable',mem.get('MemFree'))
 if total and available is not None:m.update(memory_percent=round((total-available)*100/total,1),memory_used_gb=round((total-available)/1073741824,2),memory_total_gb=round(total/1073741824,2))
 def cpu():
  a=list(map(int,open('/proc/stat').readline().split()[1:]));return sum(a[:8]),a[3]+(a[4] if len(a)>4 else 0)
 a=cpu();time.sleep(.15);b=cpu()
 if b[0]>a[0]:m['cpu_percent']=round(100*(1-(b[1]-a[1])/(b[0]-a[0])),1)
elif platform.system()=='Darwin':
 total=int(subprocess.check_output(['/usr/sbin/sysctl','-n','hw.memsize'],timeout=1).decode().strip())
 raw=subprocess.check_output(['/usr/bin/vm_stat'],timeout=1).decode();page=int(re.search(r'page size of (\d+)',raw).group(1));counts={k:int(v) for k,v in re.findall(r'^([^:]+):\s+(\d+)',raw,re.M)}
 available=sum(counts.get(k,0) for k in ['Pages free','Pages inactive','Pages speculative'])*page;available=min(total,available)
 m.update(memory_percent=round((total-available)*100/total,1),memory_used_gb=round((total-available)/1073741824,2),memory_total_gb=round(total/1073741824,2))
print(json.dumps({'system':platform.system(),'metrics':m}))'''
WINDOWS_PROBE = r'''[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new();$ProgressPreference='SilentlyContinue';$ErrorActionPreference='Stop';$o=Get-CimInstance Win32_OperatingSystem;$d=Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'";$c=(Get-CimInstance Win32_Processor|Measure-Object -Property LoadPercentage -Average).Average;$t=[double]$o.TotalVisibleMemorySize*1024;$f=[double]$o.FreePhysicalMemory*1024;@{system='Windows';metrics=@{cpu_percent=$c;memory_percent=[math]::Round(100*($t-$f)/$t,1);memory_used_gb=[math]::Round(($t-$f)/1GB,2);memory_total_gb=[math]::Round($t/1GB,2);disk_percent=[math]::Round(100*($d.Size-$d.FreeSpace)/$d.Size,1);disk_free_gb=[math]::Round($d.FreeSpace/1GB,2);disk_total_gb=[math]::Round($d.Size/1GB,2)}}|ConvertTo-Json -Compress'''


def now_iso():
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def as_time(value):
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return datetime.fromtimestamp(value, timezone.utc)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=SHANGHAI)
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return None


def age_seconds(value):
    parsed = as_time(value)
    return (datetime.now(timezone.utc) - parsed).total_seconds() if parsed else None


def safe_text(value, limit=2000):
    """Redact common credential forms; never publish source metadata wholesale."""
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"(?i)\b(?:sk-[a-z0-9_-]{12,}|gh[pousr]_[a-z0-9_]{16,}|github_pat_[a-z0-9_]{12,}|AIza[a-z0-9_-]{20,})\b", "[凭据已隐去]", text)
    text = re.sub(r"(?i)\bBearer\s+[a-z0-9._~+/=-]+", "Bearer [已隐去]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|token|密钥|密码|凭据)\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;，；]+)", r"\1[已隐去]", text)
    text = re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[已隐去]@", text)
    return text[:limit]


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\x00-\x20]", value):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
            return None
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))
    except ValueError:
        return None


def numeric(value, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if value < minimum or (maximum is not None and value > maximum):
        return None
    return value


class SourcesService:
    def __init__(self, store, data_dir, task_root=None, start_background=True):
        self.store = store
        self.data_dir = Path(data_dir)
        self.task_root = Path(task_root) if task_root is not None else TASK_ROOT
        self._lock = threading.RLock()
        self._refresh_locks = {k: threading.Lock() for k in ("tasks", "discover", "devices", "agents", "trending", "leaderboards")}
        self._closed = threading.Event()
        self._threads = []
        self._seed_devices()
        self._seed_agents()
        self.refresh("tasks")
        self._refresh_devices(include_remote=False)
        self.refresh("agents")
        if start_background:
            for kind in ("discover", "devices", "trending", "leaderboards"):
                thread = threading.Thread(target=self._background_first, args=(kind,), daemon=True, name="workbench-first-" + kind)
                self._threads.append(thread)
                thread.start()

    def close(self):
        self._closed.set()

    shutdown = close

    def _background_first(self, kind):
        if not self._closed.is_set():
            self.refresh(kind)

    def _get(self, key, default):
        return copy.deepcopy(self.store.get("sources." + key, default))

    def _set(self, key, value):
        self.store.set("sources." + key, value)

    def refresh(self, kind="all", entity_id=None):
        if kind == "news":
            kind = "discover"
        if kind not in self._refresh_locks and kind != "all":
            raise ValueError("未知采集模块")
        if self._closed.is_set():
            return {"ok": False, "status": "closed"}
        kinds = list(self._refresh_locks) if kind == "all" else [kind]
        results = {}
        for item in kinds:
            lock = self._refresh_locks[item]
            if not lock.acquire(blocking=False):
                results[item] = {"status": "busy"}
                continue
            try:
                if item == "tasks":
                    results[item] = self._refresh_tasks()
                elif item == "discover":
                    results[item] = self._refresh_discover()
                elif item == "trending":
                    results[item] = self._refresh_trending()
                elif item == "leaderboards":
                    results[item] = self._refresh_leaderboards()
                elif item == "devices":
                    results[item] = self._refresh_devices(entity_id=entity_id)
                else:
                    results[item] = self._refresh_agents(entity_id=entity_id)
            except KeyError:
                raise
            except Exception as exc:
                # Isolation prevents an unavailable external source stopping the app.
                results[item] = {"status": "error", "error": self._error_message(exc)}
            finally:
                lock.release()
        return {"ok": True, "results": results, "updated_at": now_iso()}

    @staticmethod
    def _error_message(exc):
        if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError)):
            return "采集超时；设备状态未知"
        if isinstance(exc, PermissionError):
            return "来源无读取权限"
        if isinstance(exc, (TimeoutError, URLError, ConnectionError, OSError)):
            return "来源连接失败；保留上次成功快照"
        return "来源数据读取失败（%s）" % type(exc).__name__

    # ---- Task archive: fixed whitelist, safe YAML, per-file cache ----
    @staticmethod
    def _parse_task(path):
        if path.stat().st_size > 256 * 1024:
            raise ValueError("任务档案过大")
        text = path.read_text(encoding="utf-8")
        match = re.match(r"\A\ufeff?---\s*\n(.*?)\n---\s*(?:\n|$)(.*)\Z", text, re.S)
        if not match:
            raise ValueError("缺少 YAML 档案头")
        meta = yaml.safe_load(match.group(1))
        if not isinstance(meta, dict):
            raise ValueError("档案头格式错误")
        task_id = str(meta.get("id") or path.stem)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", task_id):
            raise ValueError("任务标识格式错误")
        if not isinstance(meta.get("title"), str) or not meta["title"].strip():
            raise ValueError("缺少任务标题")
        sections = {}
        heading = None
        for line in match.group(2).splitlines():
            found = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if found:
                heading = found.group(1)
                sections.setdefault(heading, [])
            elif heading is not None:
                sections[heading].append(line)

        def section(prefix):
            for name, lines in sections.items():
                if name.startswith(prefix):
                    return lines
            return []

        def entries(prefix, count=40):
            return [safe_text(re.sub(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)", "", line).strip(), 1200)
                    for line in section(prefix) if line.strip()][:count]

        priority = meta.get("priority")
        if isinstance(priority, str) and priority.upper().startswith("P"):
            priority = priority[1:]
        try:
            priority = int(priority) if priority is not None and not isinstance(priority, bool) else None
        except (TypeError, ValueError):
            priority = None
        if priority not in (0, 1, 2):
            priority = None
        parent = meta.get("parent")
        if parent is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(parent)):
            parent = None
        updated = meta.get("updated")
        if isinstance(updated, (date, datetime)):
            updated = updated.isoformat()
        # Do not include workspace/repo/secrets, arbitrary YAML or entire body.
        return {"id": task_id, "title": safe_text(meta["title"], 160), "priority": priority,
                "status": safe_text(meta.get("status", "unknown"), 80),
                "status_label": safe_text(meta.get("status_label"), 100),
                "brief": safe_text(meta.get("brief"), 600),
                "summary": safe_text("\n".join(section("概要")).strip(), 6000),
                "blockers": entries("当前卡点"), "next": entries("下一步"),
                "log": entries("事件日志", 80), "parent": str(parent) if parent else None,
                "updated": safe_text(updated, 100), "source_status": "ready"}

    def _refresh_tasks(self):
        previous = self._get("tasks.files", {})
        errors, current, seen_ids = [], {}, set()
        observed = now_iso()
        try:
            # pathlib.glob can silently turn macOS TCC/permission failures into
            # an empty iterator. Explicit enumeration must succeed before an
            # empty archive can be reported as ready.
            if not stat.S_ISDIR(self.task_root.stat().st_mode):
                raise NotADirectoryError()
            paths = sorted(path for path in self.task_root.iterdir() if path.suffix.lower() == ".md")
        except OSError as exc:
            items = []
            for value in previous.values():
                value["source_status"] = "unavailable"
                items.append(value)
            message = "任务来源无读取权限；显示上次成功快照" if isinstance(exc, PermissionError) else "任务来源盘未挂载或目录不可读；显示上次成功快照"
            self._set("tasks.cache", {"items": items, "errors": [message],
                                      "updated_at": observed, "source_status": "unavailable"})
            return {"status": "unavailable", "count": len(items)}
        for path in paths:
            try:
                # A task-file symlink must not escape the configured archive.
                path.resolve().relative_to(self.task_root.resolve())
                item = self._parse_task(path)
                if item["id"] in seen_ids:
                    raise ValueError("重复任务标识")
                seen_ids.add(item["id"])
                current[path.name] = item
            except (OSError, UnicodeError, ValueError, yaml.YAMLError, RecursionError):
                errors.append("%s：档案损坏或不可读，保留该文件上次成功快照" % safe_text(path.name, 120))
                if path.name in previous:
                    item = previous[path.name]
                    item["source_status"] = "stale"
                    if item["id"] not in seen_ids:
                        current[path.name] = item
                        seen_ids.add(item["id"])
        for name, value in previous.items():
            if name not in current and not any(p.name == name for p in paths):
                value["source_status"] = "missing"
                if value["id"] not in seen_ids:
                    current[name] = value
                    seen_ids.add(value["id"])
                errors.append("%s：来源文件缺失，显示上次成功快照" % safe_text(name, 120))
        items = sorted(current.values(), key=lambda x: (x.get("priority") if x.get("priority") is not None else 9, x["id"]))
        self._set("tasks.files", current)
        self._set("tasks.cache", {"items": items, "errors": errors, "updated_at": observed,
                                  "source_status": "partial" if errors else "ready"})
        return {"status": "partial" if errors else "ready", "count": len(items)}

    def tasks(self):
        return self._get("tasks.cache", {"items": [], "errors": [], "updated_at": None, "source_status": "unavailable"})

    # ---- HTTP sources: bounded, conditional, cache-aware ----
    @staticmethod
    def _request(url, headers=None, timeout=5):
        request_headers = {"User-Agent": "PersonalWorkbench/1.0 (local personal use)",
                           "Accept": "application/json", "Accept-Encoding": "gzip"}
        request_headers.update(headers or {})
        request = Request(url, headers=request_headers, method="GET")
        try:
            requested = urlsplit(url)
            if requested.hostname in ("github.com", "aihot.news"):
                class SameRepositoryRedirect(HTTPRedirectHandler):
                    def redirect_request(self, req, fp, code, msg, response_headers, newurl):
                        target = urlsplit(newurl)
                        if (target.scheme != "https" or target.hostname != requested.hostname or
                                target.port not in (None, 443) or target.username or target.password or
                                target.path.rstrip("/").casefold() != requested.path.rstrip("/").casefold() or
                                target.query != requested.query):
                            raise URLError("公开页面跳转到不同来源")
                        return super().redirect_request(req, fp, code, msg, response_headers, newurl)
                response = build_opener(SameRepositoryRedirect()).open(request, timeout=timeout)
            else:
                response = urlopen(request, timeout=timeout)
        except HTTPError as exc:
            if exc.code in (304, 429, 503):
                return exc.code, None, dict(exc.headers)
            raise
        with response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError("来源响应过大")
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                    raw = compressed.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise ValueError("解压后响应过大")
            return response.status, raw, dict(response.headers)

    @staticmethod
    def _header(headers, name):
        return next((v for k, v in headers.items() if k.lower() == name.lower()), None)

    @staticmethod
    def _cache_seconds(headers):
        cache = SourcesService._header(headers, "Cache-Control") or ""
        found = re.search(r"(?:s-maxage|max-age)\s*=\s*(\d+)", cache, re.I)
        return max(60, min(86400, int(found.group(1)))) if found else 60

    @staticmethod
    def _retry_seconds(headers):
        value = SourcesService._header(headers, "Retry-After")
        try:
            return max(60, min(86400, int(value)))
        except (TypeError, ValueError):
            try:
                dt = parsedate_to_datetime(value)
                return max(60, min(86400, int((dt - datetime.now(timezone.utc)).total_seconds())))
            except (TypeError, ValueError, OverflowError):
                return 300

    @staticmethod
    def _news_item(raw, fetched):
        if not isinstance(raw, dict) or not isinstance(raw.get("title"), str):
            return None
        links = raw.get("links") if isinstance(raw.get("links"), dict) else {}
        canonical = safe_url(links.get("aihot"))
        original = safe_url(links.get("original"))
        url = original or canonical
        if not url:
            return None
        identity = str(raw.get("id") or hashlib.sha256(url.encode()).hexdigest()[:24])
        source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        attr = raw.get("attribution") if isinstance(raw.get("attribution"), dict) else {}
        category = safe_text(raw.get("category"), 80)
        url_parts = urlsplit(original or "")
        repo_parts = url_parts.path.strip("/").split("/")
        is_project = url_parts.hostname == "github.com" and len(repo_parts) == 2 and all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in repo_parts)
        return {"id": "aihot:" + safe_text(identity, 128), "kind": "project" if is_project else "news", "title": safe_text(raw["title"], 240),
                "summary": safe_text(raw.get("summary"), 1600), "url": url,
                "canonical_url": canonical, "original_url": original,
                "source": safe_text(source.get("name") or "AIHOT", 100),
                "attribution": {"name": safe_text(attr.get("name") or "AIHOT", 100), "url": safe_url(attr.get("url")) or "https://aihot.news"},
                "published_at": safe_text(raw.get("publishedAt"), 100) or None,
                "fetched_at": fetched, "tags": [category] if category else [],
                "reason": safe_text(raw.get("reason"), 1000), "license": None,
                "bookmarked": False, "trial_status": None}

    def _refresh_discover(self):
        cached = self._get("discover.cache", {"items": [], "status": "loading", "error": None, "updated_at": None})
        http = self._get("discover.http", {})
        if time.time() < http.get("next_allowed", 0):
            return {"status": "cached", "next_allowed_at": datetime.fromtimestamp(http["next_allowed"], SHANGHAI).isoformat()}
        headers = {"If-None-Match": http["etag"]} if http.get("etag") else {}
        fetched = now_iso()
        try:
            status, body, response_headers = self._request(AIHOT_URL, headers, timeout=7)
            if status in (429, 503):
                http["next_allowed"] = time.time() + self._retry_seconds(response_headers)
                cached.update(status="rate_limited" if status == 429 else "unavailable", error="资讯来源暂不可用，已按来源要求延后刷新", attempted_at=fetched)
            elif status == 304:
                http["next_allowed"] = time.time() + self._cache_seconds(response_headers)
                cached.update(status="ready", error=None, checked_at=fetched)
            elif status == 200:
                payload = json.loads(body)
                if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                    raise ValueError("资讯格式变化")
                items = [item for raw in payload["items"][:100] for item in [self._news_item(raw, fetched)] if item]
                # Personal saved records have their own durable snapshots, not
                # the retention lifetime of a changing upstream feed.
                with self._lock:
                    saved = self._get("discover.saved", {})
                    metadata = self._get("discover.meta", {})
                    for old_item in cached.get("items", []):
                        personal = metadata.get(old_item["id"], {})
                        if personal.get("bookmarked") or personal.get("trial_status"):
                            saved.setdefault(old_item["id"], dict(old_item, **personal))
                    for item in items:
                        if item["id"] in saved:
                            # A news item may refer to a repository also enriched
                            # by the daily list. Keep its last observed growth
                            # fields when the news API has no such information.
                            saved[item["id"]] = self._discovery_snapshot(dict(saved[item["id"]], **item))
                    self._set("discover.saved", saved)
                http.update(next_allowed=time.time() + self._cache_seconds(response_headers), etag=self._header(response_headers, "ETag"))
                cached = {"items": items, "status": "ready", "error": None, "updated_at": fetched, "checked_at": fetched,
                          "source_url": "https://aihot.news", "terms_url": "https://aihot.news/terms"}
            else:
                raise ValueError("资讯响应状态异常")
        except Exception as exc:
            http["next_allowed"] = time.time() + 60
            cached.update(status="unavailable", error=self._error_message(exc), attempted_at=fetched)
        self._set("discover.http", http)
        self._set("discover.cache", cached)
        return {"status": cached["status"], "count": len(cached.get("items", []))}

    def _refresh_html_collection(self, key, url, parser, min_interval):
        """Fixed public pages, parsed as data; failures never erase a good snapshot."""
        cached = self._get(key + ".cache", {"items": [], "status": "loading", "error": None,
                                          "updated_at": None, "source_url": url})
        http = self._get(key + ".http", {})
        if time.time() < http.get("next_allowed", 0):
            return {"status": "cached", "count": len(cached.get("items", [])),
                    "next_allowed_at": datetime.fromtimestamp(http["next_allowed"], SHANGHAI).isoformat()}
        headers = {"Accept": "text/html"}
        if http.get("etag"):
            headers["If-None-Match"] = http["etag"]
        fetched = now_iso()
        try:
            status, body, response_headers = self._request(url, headers, timeout=7)
            if status in (429, 503):
                http["next_allowed"] = time.time() + self._retry_seconds(response_headers)
                cached.update(status="rate_limited" if status == 429 else "unavailable",
                              error="来源暂不可用，已延后刷新", attempted_at=fetched)
            elif status == 304:
                if not cached.get("items"):
                    raise ValueError("来源返回未变更，但本地没有有效快照")
                http["next_allowed"] = time.time() + max(min_interval, self._cache_seconds(response_headers))
                cached.update(status="ready", error=None, checked_at=fetched)
            elif status == 200:
                content_type = self._header(response_headers, "Content-Type") or ""
                if content_type and "html" not in content_type.lower():
                    raise ValueError("公开页面格式变化")
                parsed = parser(body.decode("utf-8"), fetched)
                if not isinstance(parsed, dict) or not parsed.get("items"):
                    raise ValueError("公开页面没有有效条目")
                with self._lock:
                    if key == "discover.trending":
                        saved = self._get("discover.saved", {})
                        meta = self._get("discover.meta", {})
                        referenced = self._referenced_discovery_ids()

                        def normalized_url(value):
                            normalized = safe_url(value)
                            if normalized and urlsplit(normalized).hostname == "github.com":
                                normalized = normalized.rstrip("/").lower()
                            return normalized

                        # Capture the resolved personal identity, rather than
                        # only the raw GitHub ID about to leave the daily list.
                        for old in self.discover()["items"]:
                            identities = [old["id"]] + old.get("alias_ids", [])
                            if old.get("bookmarked") or old.get("trial_status") or referenced.intersection(identities):
                                for identity in identities:
                                    saved[identity] = self._discovery_snapshot(dict(old, id=identity))
                                    meta.setdefault(identity, {})["primary_id"] = old["id"]
                        incoming = {normalized_url(item["url"]): item for item in parsed["items"]}
                        for identity, old in list(saved.items()):
                            item = incoming.get(normalized_url(old.get("url")))
                            if item is not None:
                                personal = meta.get(identity, {})
                                updated = {**old, **item, "id": identity,
                                           "bookmarked": personal.get("bookmarked", old.get("bookmarked", False)),
                                           "trial_status": personal.get("trial_status", old.get("trial_status"))}
                                if identity != item["id"]:
                                    updated["source_item_id"] = item["id"]
                                saved[identity] = self._discovery_snapshot(updated)
                        self._set("discover.meta", meta)
                        self._set("discover.saved", saved)
                http.update(next_allowed=time.time() + max(min_interval, self._cache_seconds(response_headers)),
                            etag=self._header(response_headers, "ETag"))
                cached = dict(parsed, status="ready", error=None, updated_at=fetched, checked_at=fetched,
                              source_url=url)
            else:
                raise ValueError("公开页面响应状态异常")
        except Exception:
            http["next_allowed"] = time.time() + 60
            cached.update(status="unavailable", error="来源连接或页面解析失败，保留上次成功内容", attempted_at=fetched)
        self._set(key + ".http", http)
        self._set(key + ".cache", cached)
        return {"status": cached["status"], "count": len(cached.get("items", []))}

    def _refresh_trending(self):
        from workbench.trending import parse_trending

        def parse(html, fetched):
            items = []
            for row in parse_trending(html):
                row = dict(row)
                for field, limit in (("title", 240), ("repository", 240), ("summary", 1600), ("language", 80)):
                    if row.get(field) is not None:
                        row[field] = safe_text(row[field], limit)
                url = row["url"]
                items.append(dict(row, id="github:" + hashlib.sha256(url.lower().encode()).hexdigest()[:20],
                                  kind="project", daily_trending=True, source="GitHub Trending",
                                  source_url=TRENDING_URL, original_url=url,
                                  attribution={"name": "GitHub Trending", "url": TRENDING_URL},
                                  fetched_at=fetched, published_at=None, tags=[row["language"]] if row.get("language") else [],
                                  reason="GitHub 日榜 · 今日新增 Star", bookmarked=False, trial_status=None))
            return {"items": items, "window_label": "GitHub 日榜 · 今日新增 Star"}

        return self._refresh_html_collection("discover.trending", TRENDING_URL, parse, 1800)

    def _refresh_leaderboards(self):
        from workbench.leaderboard import parse_leaderboard

        def refresh_one(category):
            return category, self._refresh_html_collection(
                "discover.leaderboards." + category, LEADERBOARD_URLS[category],
                lambda html, fetched: parse_leaderboard(html), 900)

        # Each category has its own cache/backoff and cannot erase another one.
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = dict(pool.map(refresh_one, LEADERBOARD_URLS))
        return {"categories": results}

    def _public_collection(self, key, url, ttl):
        value = self._get(key + ".cache", {"items": [], "status": "loading", "error": None,
                                         "updated_at": None, "source_url": url})
        age = age_seconds(value.get("checked_at") or value.get("updated_at"))
        value["stale"] = bool(value.get("items")) and (value.get("status") != "ready" or age is None or age > ttl)
        return value

    def discover(self):
        collection = self._get("discover.cache", {"items": [], "status": "loading", "error": None, "updated_at": None})
        meta = self._get("discover.meta", {})
        projects = self._get("discover.projects", [])
        trending = self._public_collection("discover.trending", TRENDING_URL, 7200)
        saved = self._get("discover.saved", {})
        settings = self.store.get("settings", {}) or {}
        raw_interests = settings.get("interests", [])
        if not isinstance(raw_interests, list):
            raw_interests = []
        interests = list(dict.fromkeys(safe_text(x, 100).strip() for x in raw_interests[:30] if isinstance(x, str) and x.strip()))
        current_ids = {item["id"] for item in collection.get("items", []) + trending.get("items", [])}
        referenced_ids = self._referenced_discovery_ids()
        # Current source data takes precedence over an older saved snapshot.
        current_by_id = {}
        for item in trending.get("items", []) + projects + collection.get("items", []):
            if item["id"] not in current_by_id:
                current_by_id[item["id"]] = dict(item)
            else:
                current_by_id[item["id"]] = dict(item, **current_by_id[item["id"]])
        merged = list(current_by_id.values()) + [dict(item, outside_current_window=True) for item_id, item in saved.items() if item_id not in current_ids and item_id not in current_by_id]
        def normalized_url(value):
            normalized = safe_url(value)
            if normalized and urlsplit(normalized).hostname == "github.com":
                normalized = normalized.rstrip("/").lower()
            return normalized

        groups = {}
        for item in merged:
            normalized = normalized_url(item.get("url"))
            if normalized:
                groups.setdefault(normalized, []).append(item)
        trending_urls = {normalized_url(item.get("url")) for item in trending.get("items", [])}
        saved_by_url = {}
        for item in saved.values():
            normalized = normalized_url(item.get("url"))
            if normalized:
                saved_by_url.setdefault(normalized, []).append(item)
        by_url = {}
        for normalized, group in groups.items():
            # The first live source supplies content; all known identities
            # supply personal state. Referenced IDs have priority over stars
            # and trial state, while aliases remain addressable endpoints.
            value = dict(group[0])
            source_id = value["id"]
            members = {}
            for item in group:
                identity = item["id"]
                personal = meta.get(identity, {})
                members[identity] = {"bookmarked": bool(personal.get("bookmarked", item.get("bookmarked", False))),
                                     "trial_status": personal.get("trial_status", item.get("trial_status"))}
                for field in ("license", "metadata_status", "metadata_source", "metadata_checked_at", "repository_updated_at"):
                    if not value.get(field) and item.get(field):
                        value[field] = item[field]
            for item in group:
                aliases = list(item.get("alias_ids") or [])
                if isinstance(item.get("source_item_id"), str):
                    aliases.append(item["source_item_id"])
                for identity in aliases:
                    if isinstance(identity, str) and identity not in members:
                        personal = meta.get(identity, {})
                        members[identity] = {"bookmarked": bool(personal.get("bookmarked", False)),
                                             "trial_status": personal.get("trial_status")}
            preferred = {meta.get(identity, {}).get("primary_id") for identity in members}

            def priority(identity):
                personal = members[identity]
                return (identity not in referenced_ids, not personal["bookmarked"],
                        not bool(personal["trial_status"]), identity not in preferred, identity)

            personal_ids = [identity for identity, personal in members.items()
                            if identity in referenced_ids or personal["bookmarked"] or personal["trial_status"]]
            hinted_ids = [identity for identity in members if identity in preferred]
            primary = min(personal_ids or hinted_ids, key=priority) if personal_ids or hinted_ids else source_id
            value["id"] = primary
            value["alias_ids"] = sorted(identity for identity in members if identity != primary)
            if primary != source_id:
                value["source_item_id"] = source_id
            value["bookmarked"] = any(personal["bookmarked"] for personal in members.values())
            value["trial_status"] = next((members[identity]["trial_status"] for identity in sorted(members, key=priority)
                                           if members[identity]["trial_status"]), None)
            # A persistent manual record can outlive the daily list. Show its
            # most recent saved daily metrics rather than its original ones.
            historical = [item for item in saved_by_url.get(normalized, []) if item.get("stars_today") is not None]
            if normalized not in trending_urls and historical:
                latest = max(historical, key=lambda item: (as_time(item.get("fetched_at")) or datetime.min.replace(tzinfo=timezone.utc)))
                for field in ("repository", "language", "total_stars", "stars_today", "trending_rank", "growth_window", "daily_trending", "source_url", "fetched_at"):
                    if field in latest:
                        value[field] = latest[field]
                value["outside_current_window"] = True
            searchable = " ".join([str(value.get("title") or ""), str(value.get("summary") or ""), " ".join(str(x) for x in value.get("tags", []))]).casefold()
            searchable = re.sub(r"\s+", " ", searchable)
            matches = []
            for interest in interests:
                term = re.sub(r"\s+", " ", interest.casefold())
                # ASCII words match word boundaries (AI must not match
                # "said"); Chinese interests use literal substring match.
                pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])" if re.fullmatch(r"[a-z0-9 ._+/-]+", term) else re.escape(term)
                if re.search(pattern, searchable):
                    matches.append(interest)
            value["interest_matches"] = matches
            value["is_relevant"] = bool(matches)
            by_url[normalized] = value
        collection["items"] = list(by_url.values())
        collection["interests"] = interests
        # Resolve IDs after URL de-duplication so an existing personal identity
        # remains the same endpoint for bookmarks, trials and relationships.
        trending["item_ids"] = [by_url[normalized_url(row["url"])]["id"]
                                for row in trending.get("items", [])
                                if normalized_url(row["url"]) in by_url]
        trending.pop("items", None)
        collection["trending"] = trending
        collection["leaderboards"] = {"categories": {
            kind: self._public_collection("discover.leaderboards." + kind, url, 3600)
            for kind, url in LEADERBOARD_URLS.items()}}
        return collection

    def _referenced_discovery_ids(self):
        return {relation.get(side + "_id") for relation in (self.store.get("relations", []) or [])
                if isinstance(relation, dict) for side in ("from", "to")
                if relation.get(side + "_type") == "discover" and isinstance(relation.get(side + "_id"), str)}

    @staticmethod
    def _discovery_snapshot(item):
        fields = ("id", "kind", "title", "summary", "url", "source", "published_at", "fetched_at", "tags", "reason", "license",
                  "attribution", "canonical_url", "original_url", "metadata_status", "metadata_source", "metadata_checked_at",
                  "repository_updated_at", "bookmarked", "trial_status", "source_item_id",
                  "repository", "language", "total_stars", "stars_today", "trending_rank", "growth_window",
                  "daily_trending", "source_url")
        snapshot = {key: copy.deepcopy(item[key]) for key in fields if key in item}
        for key, limit in (("title", 240), ("summary", 1600), ("source", 100), ("reason", 1000), ("trial_status", 60),
                           ("repository", 240), ("language", 80), ("growth_window", 30)):
            if key in snapshot:
                snapshot[key] = safe_text(snapshot[key], limit) or (None if key == "trial_status" else "")
        for key in ("url", "canonical_url", "original_url", "source_url"):
            if key in snapshot:
                snapshot[key] = safe_url(snapshot[key])
        snapshot["tags"] = [safe_text(tag, 80) for tag in (item.get("tags") or [])[:30] if isinstance(tag, str)]
        attribution = item.get("attribution")
        if isinstance(attribution, dict):
            snapshot["attribution"] = {"name": safe_text(attribution.get("name"), 100), "url": safe_url(attribution.get("url"))}
        return snapshot

    def preserve_discovery(self, item_id):
        """Retain a relation endpoint without changing the user's bookmark."""
        with self._lock:
            item = next((item for item in self.discover()["items"]
                         if item["id"] == item_id or item_id in item.get("alias_ids", [])), None)
            if item is None:
                raise KeyError(item_id)
            saved = self._get("discover.saved", {})
            meta = self._get("discover.meta", {})
            for identity in [item["id"]] + item.get("alias_ids", []):
                saved[identity] = self._discovery_snapshot(dict(item, id=identity))
                meta.setdefault(identity, {})["primary_id"] = item["id"]
            self._set("discover.meta", meta)
            self._set("discover.saved", saved)
        return {"ok": True, "id": item_id}

    def discover_meta(self, item_id, payload):
        changes = {}
        if "bookmarked" in payload:
            if not isinstance(payload["bookmarked"], bool):
                raise ValueError("收藏状态必须为布尔值")
            changes["bookmarked"] = payload["bookmarked"]
        if "trial_status" in payload:
            value = payload["trial_status"]
            if value is not None and not isinstance(value, str):
                raise ValueError("试用状态格式错误")
            changes["trial_status"] = safe_text(value, 60) or None
        with self._lock:
            item = next((x for x in self.discover()["items"]
                         if x["id"] == item_id or item_id in x.get("alias_ids", [])), None)
            if item is None:
                raise KeyError(item_id)
            meta = self._get("discover.meta", {})
            saved = self._get("discover.saved", {})
            identities = [item["id"]] + item.get("alias_ids", [])
            updated = {"bookmarked": bool(item.get("bookmarked")), "trial_status": item.get("trial_status"),
                       "primary_id": item["id"], **changes}
            preserve = updated["bookmarked"] or updated["trial_status"] or self._referenced_discovery_ids().intersection(identities)
            # Apply the shared state to every alias so a stale saved star or
            # trial cannot reappear when another source leaves the group.
            for identity in identities:
                meta.setdefault(identity, {}).update(updated)
                if preserve:
                    saved[identity] = self._discovery_snapshot(dict(item, id=identity, **updated))
                else:
                    saved.pop(identity, None)
            self._set("discover.meta", meta)
            self._set("discover.saved", saved)
        return {"ok": True, "id": item_id}

    @staticmethod
    def _github_page_fields(payload, owner, repo):
        """Read GitHub's public JSON view without interpreting its README HTML."""
        if not isinstance(payload, dict):
            raise ValueError("公开仓库页面格式变化")
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        title = meta.get("title")
        route = (payload.get("payload") or {}).get("codeViewRepoRoute") if isinstance(payload.get("payload"), dict) else None
        if not isinstance(title, str) or not isinstance(route, dict):
            raise ValueError("公开仓库信息不可识别")
        title = re.sub(r"\s*[·|]\s*GitHub\s*$", "", title)
        match = re.fullmatch(r"(?:GitHub\s*-\s*)?" + re.escape(owner + "/" + repo) + r"(?:\s*:\s*(.*))?", title, re.I | re.S)
        if not match:
            raise ValueError("公开页面不是同一仓库")
        about = route.get("about") if isinstance(route.get("about"), dict) else {}
        description = about.get("description") or route.get("description") or match.group(1)
        description = description if isinstance(description, str) else None
        raw_topics = about.get("topics") or route.get("topics") or []
        topics = []
        if isinstance(raw_topics, list):
            for topic in raw_topics[:15]:
                value = topic.get("name") if isinstance(topic, dict) else topic
                if isinstance(value, str):
                    topics.append(safe_text(value, 80))
        license_id = None
        overview = route.get("overview") if isinstance(route.get("overview"), dict) else {}
        files = overview.get("overviewFiles") if isinstance(overview.get("overviewFiles"), list) else []
        for item in files[:30]:
            if not isinstance(item, dict):
                continue
            if not re.fullmatch(r"(?:LICENSE|LICENCE|COPYING|UNLICENSE)(?:[._-].*)?", str(item.get("displayName") or ""), re.I):
                continue
            label = item.get("tabName")
            # The page label is GitHub's recognized license. A generic
            # "License" tab or merely a LICENSE file proves no license ID.
            if isinstance(label, str) and (label in {"MIT", "ISC", "Unlicense", "Zlib"} or re.fullmatch(r"[A-Za-z0-9.+-]+-\d+(?:\.\d+)*(?:-[A-Za-z0-9.+-]+)?", label)):
                license_id = safe_text(label, 80)
                break
        return {"summary": safe_text(description, 1600), "tags": topics, "license": license_id,
                "metadata_status": "ready", "metadata_source": "github-public-page"}

    def add_project(self, payload):
        url = safe_url(payload.get("url"))
        parts = urlsplit(url or "")
        segments = parts.path.strip("/").split("/")
        if parts.hostname != "github.com" or len(segments) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", p) for p in segments):
            raise ValueError("请输入 GitHub 仓库首页链接，例如 https://github.com/owner/repo")
        owner, repo = segments
        repo = repo[:-4] if repo.endswith(".git") else repo
        if not repo or owner in (".", "..") or repo in (".", ".."):
            raise ValueError("仓库链接格式错误")
        url = "https://github.com/%s/%s" % (owner, repo)
        existing = next((item for item in self.discover()["items"] if item.get("url", "").rstrip("/").lower() == url.lower()), None)
        if existing and existing.get("metadata_status") not in ("unknown", "unavailable"):
            return {"ok": True, "id": existing["id"], "existing": True}
        item_id = existing["id"] if existing else "github:" + hashlib.sha256(url.lower().encode()).hexdigest()[:20]
        item = dict(existing) if existing else {"id": item_id, "kind": "project", "title": "%s/%s" % (owner, repo),
                "summary": safe_text(payload.get("summary"), 1600), "url": url, "source": "GitHub",
                "published_at": None, "fetched_at": now_iso(), "tags": [], "reason": "手动添加的开源项目",
                "license": None, "bookmarked": False, "trial_status": None, "metadata_status": "unknown"}
        item.update(fetched_at=now_iso(), metadata_checked_at=now_iso())
        preserved_summary = safe_text(payload.get("summary") or (existing or {}).get("summary"), 1600)
        api_succeeded = False
        try:
            if time.time() < self._get("github.api_until", 0):
                raise ConnectionError("GitHub API 暂在冷却期")
            status, body, _ = self._request("https://api.github.com/repos/%s/%s" % (owner, repo), timeout=5)
            if status == 200:
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError("仓库信息格式变化")
                if data.get("full_name", owner + "/" + repo).casefold() != (owner + "/" + repo).casefold():
                    raise ValueError("仓库接口已跳转到不同仓库")
                topics = data.get("topics") if isinstance(data.get("topics"), list) else []
                license_data = data.get("license") if isinstance(data.get("license"), dict) else {}
                item.update(title=safe_text(data.get("full_name") or item["title"], 200),
                            summary=preserved_summary or safe_text(data.get("description"), 1600),
                            published_at=safe_text(data.get("created_at"), 100) or None,
                            tags=[safe_text(x, 80) for x in topics[:15] if isinstance(x, str)],
                            license=safe_text(license_data.get("spdx_id"), 80) or None,
                            metadata_status="ready", metadata_source="github-api", repository_updated_at=safe_text(data.get("pushed_at"), 100) or None)
                if item["license"] == "NOASSERTION":
                    item["license"] = None
                api_succeeded = True
        except HTTPError as exc:
            if exc.code in (403, 429):
                headers = dict(exc.headers or {})
                try:
                    wait_until = float(self._header(headers, "X-RateLimit-Reset"))
                except (TypeError, ValueError):
                    wait_until = time.time() + self._retry_seconds(headers)
                self._set("github.api_until", min(time.time() + 3600, max(time.time() + 60, wait_until)))
        except Exception:
            pass
        if not api_succeeded:
            try:
                status, body, _ = self._request(url, {"Accept": "application/json"}, timeout=6)
                if status != 200:
                    raise ValueError("公开仓库页面不可用")
                fields = self._github_page_fields(json.loads(body), owner, repo)
                item.update(fields)
                item["summary"] = preserved_summary or fields["summary"]
            except Exception:
                item.update(metadata_status="unavailable", metadata_source=None)
        with self._lock:
            projects = self._get("discover.projects", [])
            previous_index = next((index for index, value in enumerate(projects) if value["id"] == item_id), None)
            if previous_index is None:
                projects.append(item)
            else:
                projects[previous_index] = item
            self._set("discover.projects", projects)
            saved = self._get("discover.saved", {})
            if item_id in saved:
                saved[item_id] = dict(item)
                self._set("discover.saved", saved)
        return {"ok": True, "id": item_id, "existing": bool(existing), "refreshed": bool(existing),
                "metadata_status": item["metadata_status"], "metadata_source": item.get("metadata_source")}

    # ---- Device inventory and strictly fixed read-only probes ----
    def _seed_devices(self):
        with self._lock:
            records = self._get("devices.records", [])
            existing = {x["id"]: x for x in records}
            for seed in DEVICE_SEEDS:
                if seed["id"] not in existing:
                    records.append(dict(seed, archived=False))
                else:
                    record = existing[seed["id"]]
                    for key in ("address", "hostname", "domain", "note"):
                        if key not in record and key in seed:
                            record[key] = seed[key]
            for record in records:
                if record.get("source_kind") == "ssh" and record.get("alias") in REMOTE_HOSTS:
                    record.setdefault("address", REMOTE_HOSTS[record["alias"]])
            self._set("devices.records", records)

    def _seed_agents(self):
        with self._lock:
            records = self._get("agents.records", [])
            existing = {x["id"] for x in records}
            for seed in AGENT_SEEDS:
                if seed["id"] not in existing:
                    records.append(dict(seed, role_ids=[], hidden=False, enabled=SETTINGS["enable_ai"]))
            self._set("agents.records", records)

    @staticmethod
    def _local_metrics():
        memory = psutil.virtual_memory()
        disk = shutil.disk_usage(str(Path.home()))
        return {"cpu_percent": round(psutil.cpu_percent(interval=0.1), 1),
                "memory_percent": round(memory.percent, 1),
                "memory_used_gb": round((memory.total - memory.available) / 2 ** 30, 2),
                "memory_total_gb": round(memory.total / 2 ** 30, 2),
                "disk_percent": round((disk.total - disk.free) * 100 / disk.total, 1),
                "disk_free_gb": round(disk.free / 2 ** 30, 2), "disk_total_gb": round(disk.total / 2 ** 30, 2)}

    @staticmethod
    def _remote_metrics(alias):
        if alias not in REMOTE_HOSTS:
            raise ValueError("该来源没有允许的只读采集适配器")
        options = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=yes",
                   "-o", "UpdateHostKeys=no", "-o", "ClearAllForwardings=yes", "-o", "PermitLocalCommand=no",
                   "-o", "ControlMaster=no", "-o", "ControlPath=none", "-o", "RequestTTY=no", "-o", "LogLevel=ERROR"]
        profile = REMOTE_CONNECTIONS.get(alias, {})
        target = profile.get("target", alias)
        if profile.get("user"):
            options += ["-l", profile["user"]]
        if profile.get("identity"):
            options += ["-i", profile["identity"], "-o", "IdentitiesOnly=yes"]
        if profile.get("legacy_rsa"):
            options += ["-o", "PubkeyAcceptedAlgorithms=+ssh-rsa"]
        config = subprocess.run(["ssh", "-G"] + options + [target], capture_output=True, text=True, timeout=2, check=True)
        hostname = next((line.split(None, 1)[1] for line in config.stdout.splitlines() if line.startswith("hostname ")), "")
        if hostname.lower() != REMOTE_HOSTS[alias].lower():
            raise ValueError("SSH 别名目标与允许清单不一致")
        resolved = dict(line.split(None, 1) for line in config.stdout.splitlines() if len(line.split(None, 1)) == 2)
        if resolved.get("proxycommand", "none") != "none" or resolved.get("proxyjump", "none") != "none" or resolved.get("remotecommand", "none") != "none":
            raise ValueError("固定只读采集不使用额外跳板或预设远程命令")
        # Quote fixed probe text; no user input is interpolated into commands.
        import shlex
        # EncodedCommand avoids differences between Windows cmd and PowerShell
        # SSH login shells. The encoded payload is the fixed read-only script.
        command = ("powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(WINDOWS_PROBE.encode("utf-16le")).decode("ascii")) if alias in WINDOWS_ALIASES else "python3 -B -c " + shlex.quote(UNIX_PROBE)
        result = subprocess.run(["ssh"] + options + [target, command], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=6)
        if result.returncode != 0:
            # Never return SSH banners, remote stderr or config contents.
            stderr = result.stderr.lower()
            if "timed out" in stderr or "operation timeout" in stderr:
                raise TimeoutError("只读采集连接超时")
            if "permission denied" in stderr or "authentication failed" in stderr:
                raise PermissionError("只读采集无权限")
            raise ConnectionError("只读采集未成功")
        if len(result.stdout) > 16384:
            raise ValueError("指标响应过大")
        data = json.loads(result.stdout.strip())
        if not isinstance(data, dict) or not isinstance(data.get("metrics"), dict):
            raise ValueError("指标格式变化")
        metrics = {key: numeric(data["metrics"].get(key), maximum=100 if key.endswith("percent") else None) for key in METRIC_KEYS}
        if all(value is None for value in metrics.values()):
            raise ValueError("没有有效指标")
        return {"metrics": metrics, "detected_system": safe_text(data.get("system"), 40)}

    def _refresh_devices(self, entity_id=None, include_remote=True):
        records = self._get("devices.records", [])
        if entity_id and entity_id not in {x["id"] for x in records}:
            raise KeyError(entity_id)
        snapshots = self._get("devices.snapshots", {})
        selected = [x for x in records if not entity_id or x["id"] == entity_id]

        def collect(record):
            old = snapshots.get(record["id"], {})
            observed = now_iso()
            if record.get("archived"):
                return record["id"], dict(old, status="archived")
            if record["source_kind"] == "manual":
                return record["id"], {"status": "unconnected", "device_state": "unknown", "metrics": {k: None for k in METRIC_KEYS}, "error": None}
            if not record.get("enabled", True):
                return record["id"], dict(old, status="paused", error=None)
            if record["source_kind"] == "ssh" and not include_remote:
                return record["id"], old
            try:
                if record["source_kind"] == "local" and record["id"] == "local":
                    data = {"metrics": self._local_metrics(), "detected_system": platform.system()}
                elif record["source_kind"] == "ssh" and record.get("alias") in REMOTE_HOSTS:
                    data = self._remote_metrics(record["alias"])
                else:
                    raise ValueError("来源未接入")
                return record["id"], dict(data, status="ready", device_state="reachable", observed_at=observed,
                                          last_success_at=observed, error=None)
            except Exception as exc:
                old.update(status="unavailable", device_state="unknown", observed_at=observed, error=self._error_message(exc))
                return record["id"], old

        if include_remote:
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(collect, record) for record in selected]
                for future in as_completed(futures):
                    key, snapshot = future.result()
                    snapshots[key] = snapshot
        else:
            for record in selected:
                key, snapshot = collect(record)
                snapshots[key] = snapshot
        with self._lock:
            # Merge so a simultaneous single-device refresh cannot drop others.
            self._set("devices.snapshots", snapshots)
            self._set("devices.updated", now_iso())
        return {"status": "ready", "count": len(selected)}

    def devices(self):
        snapshots = self._get("devices.snapshots", {})
        items = []
        for record in self._get("devices.records", []):
            item = dict(record)
            item.update({"status": "unconnected", "device_state": "unknown", "metrics": {k: None for k in METRIC_KEYS},
                         "last_success_at": None, "observed_at": None, "error": None})
            item.update(snapshots.get(record["id"], {}))
            if record.get("archived"):
                item["status"] = "archived"
            elif record["source_kind"] == "manual":
                item.update(status="unconnected", device_state="unknown", metrics={k: None for k in METRIC_KEYS},
                            last_success_at=None, observed_at=None, error=None)
            elif not record.get("enabled", True):
                item["status"] = "paused"
            elif item["status"] == "ready" and (age_seconds(item["last_success_at"]) or 0) > DEVICE_TTL:
                item.update(status="stale", device_state="unknown", error="采集数据已过期；设备状态待确认")
            item["metrics"] = {key: item.get("metrics", {}).get(key) for key in METRIC_KEYS}
            items.append(item)
        return {"items": items, "updated_at": self._get("devices.updated", None)}

    def device_save(self, payload, id=None):
        with self._lock:
            records = self._get("devices.records", [])
            existing = next((x for x in records if x["id"] == id), None) if id else None
            if id and existing is None:
                raise KeyError(id)
            if existing:
                record = dict(existing)
                # A UI edit must never redirect an allowlisted probe.
                for key in ("alias", "address", "hostname", "domain"):
                    if key in payload and (payload[key] or "") != (existing.get(key) or "") and existing["source_kind"] != "manual":
                        raise ValueError("固定采集来源不能修改目标；可新增仅登记设备")
                if "source_kind" in payload and payload["source_kind"] != existing["source_kind"]:
                    raise ValueError("采集类型由允许的适配器确定")
            else:
                if payload.get("source_kind") not in (None, "manual"):
                    raise ValueError("新增设备先以仅登记方式保存")
                record = {"id": "device-" + uuid.uuid4().hex[:12], "name": "", "system": "未知", "group": "其他设备",
                          "environment": "个人", "alias": None, "source_kind": "manual", "enabled": False, "archived": False}
            for key, limit in (("name", 100), ("system", 80), ("group", 80), ("environment", 80), ("alias", 150),
                               ("address", 150), ("hostname", 150), ("domain", 200), ("note", 1000)):
                if key in payload:
                    if payload[key] is not None and not isinstance(payload[key], str):
                        raise ValueError("设备资料格式错误")
                    record[key] = safe_text(payload[key], limit) or (None if key == "alias" else "")
            if not record["name"].strip():
                raise ValueError("请填写设备名称")
            for key in ("enabled", "archived"):
                if key in payload:
                    if not isinstance(payload[key], bool):
                        raise ValueError("开关格式错误")
                    record[key] = payload[key]
            if existing:
                records[records.index(existing)] = record
            else:
                records.append(record)
            self._set("devices.records", records)
        return {"ok": True, "id": record["id"]}

    # ---- AI evidence: process, source, and business activity are separate ----
    @staticmethod
    def _process_states():
        states = {"codex": "not_running", "zcode": "not_running", "kimi": "not_running", "hermes": "unknown"}
        try:
            for process in psutil.process_iter(["name", "exe"]):
                try:
                    name = (process.info.get("name") or "").lower()
                    exe = process.info.get("exe") or ""
                    if name in ("codex", "chatgpt") or "/CodexCLI.app/" in exe:
                        states["codex"] = "online"
                    if "/ZCode.app/" in exe or name in ("zcode", "zcode-cli"):
                        states["zcode"] = "online"
                    if "/Kimi.app/" in exe or name == "kimi":
                        states["kimi"] = "online"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except (psutil.Error, OSError):
            return {key: "unknown" for key in states}
        if platform.system() == "Darwin":
            try:
                result = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=2)
                for line in result.stdout.splitlines():
                    fields = line.split()
                    if len(fields) == 3 and fields[2] == "ai.hermes.gateway":
                        states["hermes"] = "online" if fields[0].isdigit() else "not_running"
                        break
            except (OSError, subprocess.TimeoutExpired):
                pass
        return states

    @staticmethod
    def _bridge_activity(raw, platform_name, source_ts):
        if not isinstance(raw, dict):
            return None
        event_id = raw.get("id")
        if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", event_id):
            return None
        title = raw.get("t") or ""
        try:
            title = bytes.fromhex(title).decode("gb2312", errors="replace") if isinstance(title, str) else ""
        except (ValueError, UnicodeError):
            title = "活动标题无法解码"
        # Do not reveal sensitive file/credential hints in titles.
        title = safe_text(title, 120)
        title = re.sub(r"(?i)(?:/[^\s]+/)?(?:\.env(?:\.[\w-]+)?|auth\.json|credentials?\.[\w]+|id_(?:rsa|ed25519))\b", "[敏感文件]", title)
        age = numeric(raw.get("a"), maximum=365 * 86400)
        stamp = as_time(source_ts)
        last = (stamp - timedelta(seconds=age)).astimezone(SHANGHAI).isoformat(timespec="seconds") if stamp and age is not None else None
        return {"id": platform_name + ":" + event_id, "title": title or "未命名活动",
                "state": {"R": "running", "W": "completed_unread"}.get(raw.get("s"), "unknown"),
                "last_activity_at": last, "reference_kind": "activity_event", "source_event_id": event_id}

    def _hermes_snapshot(self, processes, observed):
        old = self._get("agents.snapshots", {}).get("hermes-local", {})
        snapshot = dict(old, observed_at=observed, process_state=processes.get("hermes", "unknown"), running=None, completed_unread=None,
                        activities=[], activity_label="尚无可靠的当前活动计数", source_kind="hermes-state-file")
        path = Path.home() / ".hermes" / "gateway_state.json"
        try:
            if path.stat().st_size > 256 * 1024:
                raise ValueError("状态文件过大")
            state = json.loads(path.read_text())
            pid = state.get("pid")
            if isinstance(pid, int) and not isinstance(pid, bool):
                try:
                    process = psutil.Process(pid)
                    exe = process.exe()
                    if "/.hermes/" in exe:
                        snapshot["process_state"] = "online"
                except psutil.NoSuchProcess:
                    if processes.get("hermes", "unknown") == "unknown":
                        snapshot["process_state"] = "not_running"
                except psutil.AccessDenied:
                    pass
            updated = state.get("updated_at")
            age = age_seconds(updated)
            snapshot.update(source_updated_at=updated if as_time(updated) else None,
                            source_state="stale" if age is None or age > AGENT_TTL or age < -60 else "ready",
                            snapshot_gateway_state=safe_text(state.get("gateway_state"), 50),
                            snapshot_active_agents=numeric(state.get("active_agents"), maximum=100000),
                            error="活动状态文件不是定期心跳，快照已过期" if age is None or age > AGENT_TTL else None)
            snapshot["activity_label"] = "进程%s；活动仅有历史快照" % ("在线" if snapshot["process_state"] == "online" else "状态待确认")
        except (OSError, ValueError, TypeError):
            snapshot.update(source_state="unavailable", error="Hermes 状态来源不可读；当前活动未知")
        return snapshot

    def _refresh_agents(self, entity_id=None):
        records = self._get("agents.records", [])
        if entity_id and entity_id not in {x["id"] for x in records}:
            raise KeyError(entity_id)
        snapshots = self._get("agents.snapshots", {})
        processes = self._process_states() if any(x.get("enabled", False) and (not entity_id or x["id"] == entity_id) for x in records) else {}
        observed = now_iso()
        subscribed = [x for x in records if x["platform"] != "hermes" and x.get("enabled", True) and (not entity_id or x["id"] == entity_id)]
        bridge, bridge_error = None, None
        if subscribed:
            try:
                health_status, _, _ = self._request(BRIDGE_URL + "/healthz", timeout=1.5)
                status, raw, _ = self._request(BRIDGE_URL + "/status", timeout=2)
                bridge = json.loads(raw) if status == 200 and health_status == 200 else None
                if not isinstance(bridge, dict) or as_time(bridge.get("ts")) is None:
                    raise ValueError("AI 来源格式变化")
            except Exception as exc:
                bridge_error = self._error_message(exc)
                bridge = None
        for record in records:
            if entity_id and record["id"] != entity_id:
                continue
            old = snapshots.get(record["id"], {})
            if not record.get("enabled", True):
                snapshots[record["id"]] = dict(old, source_state="paused", error=None)
                continue
            if record["platform"] == "hermes":
                snapshots[record["id"]] = self._hermes_snapshot(processes, observed)
                continue
            snapshot = dict(old, process_state=processes.get(record["platform"], "unknown"), observed_at=observed,
                            source_kind="pixelpet-bridge", source_scope="shared_bridge", activity_list_complete=False)
            raw = bridge.get(record["platform"]) if bridge else None
            if isinstance(raw, dict) and raw.get("ok") is True:
                count = numeric(raw.get("running"), maximum=1000000)
                unread = numeric(raw.get("waiting"), maximum=1000000)
                if count is not None and unread is not None and isinstance(raw.get("items"), list):
                    source_ts = bridge["ts"]
                    source_age = age_seconds(source_ts)
                    activities = [activity for item in raw["items"][:5] for activity in [self._bridge_activity(item, record["platform"], source_ts)] if activity]
                    source_at = as_time(source_ts).astimezone(SHANGHAI).isoformat(timespec="seconds")
                    label = {"codex": "来源报告；Codex 根据会话事件推断", "zcode": "来源报告；ZCode 原生任务状态", "kimi": "来源报告；Kimi 原生状态与活动计数"}[record["platform"]]
                    if count:
                        active = [x for x in activities if x["state"] == "running"]
                        recent = [age_seconds(x["last_activity_at"]) for x in active]
                        recent = [x for x in recent if x is not None]
                        if not recent or min(recent) > 600:
                            label += "；执行实时性待核实"
                    snapshot.update(source_state="ready" if source_age is not None and -60 <= source_age <= AGENT_TTL else "stale",
                                    running=int(count), completed_unread=int(unread), source_updated_at=source_at,
                                    activities=activities, activities_truncated=len(raw["items"]) >= 5 or count + unread > len(activities),
                                    activity_label=label, error=None)
                else:
                    snapshot.update(source_state="error", error="AI 来源缺少有效计数；当前活动未知")
                    if not old:
                        snapshot.update(running=None, completed_unread=None, activities=[])
            else:
                snapshot.update(source_state="unavailable" if bridge is None else "error", error=bridge_error or "该 AI 来源读取失败；保留上次快照")
                if not old:
                    snapshot.update(running=None, completed_unread=None, activities=[], source_updated_at=None)
            snapshots[record["id"]] = snapshot
        self._set("agents.snapshots", snapshots)
        self._set("agents.updated", observed)
        return {"status": "ready" if bridge is not None or not subscribed else "unavailable", "count": len(records)}

    def agents(self):
        snapshots = self._get("agents.snapshots", {})
        items = []
        for record in self._get("agents.records", []):
            item = dict(record, process_state="unknown", source_state="unconnected", running=None,
                        completed_unread=None, observed_at=None, source_updated_at=None,
                        activity_label="当前活动尚未接入", activities=[], error=None)
            item.update(snapshots.get(record["id"], {}))
            if not record.get("enabled", True):
                item["source_state"] = "paused"
            elif item["source_state"] == "ready" and (age_seconds(item.get("observed_at")) or 0) > AGENT_TTL:
                item.update(source_state="stale", error="采集快照已过期；当前状态待确认")
            if (age_seconds(item.get("observed_at")) or 0) > AGENT_TTL:
                item["process_state"] = "unknown"
            items.append(item)
        return {"items": items, "updated_at": self._get("agents.updated", None)}

    def agent_meta(self, item_id, payload):
        with self._lock:
            records = self._get("agents.records", [])
            record = next((x for x in records if x["id"] == item_id), None)
            if record is None:
                raise KeyError(item_id)
            if "name" in payload:
                if not isinstance(payload["name"], str) or not payload["name"].strip():
                    raise ValueError("请填写实例名称")
                record["name"] = safe_text(payload["name"], 100)
            for key in ("hidden", "enabled"):
                if key in payload:
                    if not isinstance(payload[key], bool):
                        raise ValueError("开关格式错误")
                    record[key] = payload[key]
            if "role_ids" in payload:
                roles = payload["role_ids"]
                if not isinstance(roles, list) or len(roles) > 50 or not all(isinstance(x, str) and len(x) <= 100 for x in roles):
                    raise ValueError("角色绑定格式错误")
                known = {x["id"] for x in (self.store.get("roles", []) or [])}
                if known and any(x not in known for x in roles):
                    raise ValueError("关联角色不存在")
                record["role_ids"] = list(dict.fromkeys(roles))
            if "group" in payload:
                record["group"] = safe_text(payload["group"], 80)
            self._set("agents.records", records)
        return {"ok": True, "id": item_id}
