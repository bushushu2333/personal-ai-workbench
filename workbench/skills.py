"""Read-only skill indexing and an isolated, versioned draft workspace.

Nothing in this module imports or executes a skill. Existing source directories
are read-only; writes are restricted to Store and the workbench's data directory.
"""

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path, PurePosixPath

import yaml


from workbench.config import SETTINGS

DEFAULT_ROOTS = [Path(root) for root in SETTINGS["skills_roots"]]
EXCLUDED_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".cache", "cache",
    ".venv", "venv", ".pytest_cache", ".mypy_cache", ".history", ".revisions",
}
SECRET_NAMES = {
    ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519", "credentials.json",
    "credential.json", "secrets.json", "secret.json", "auth.json", "tokens.json",
    "token.json", "credentials.yaml", "secrets.yaml", "credentials.yml", "secrets.yml",
}
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_FILES = 1500
MAX_MANIFEST_BYTES = 1024 * 1024
SENSITIVE_TEXT = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|"
    r"\b(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|"
    r"github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})\b"
)
SECRET_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:export\s+)?(?:[A-Z0-9_]*(?:API_KEY|ACCESS_TOKEN|SECRET_KEY|"
    r"CLIENT_SECRET|PRIVATE_KEY|PASSWORD))\s*[:=]\s*[\"']?"
    r"(?!\$|<|your[-_ ]|YOUR|example|placeholder|changeme|xxx|\*|\{|None|true|false)"
    r"[A-Za-z0-9_+/.=-]{24,}[\"']?\s*$"
)


def _now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def _within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _scalar(value, default=""):
    return str(value) if isinstance(value, (str, int, float, bool)) else default


def _text_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip(" -\t") for line in value.splitlines() if line.strip(" -\t")]
    if isinstance(value, list):
        return [_scalar(v) for v in value if _scalar(v)]
    return []


def _sensitive(data):
    # Binary resources are screened by filename. Text content is additionally
    # screened for common real credential formats, without evaluating the file.
    if b"\x00" in data[:4096]:
        return False
    text = data.decode("utf-8", errors="replace")
    return bool(SENSITIVE_TEXT.search(text) or SECRET_ASSIGNMENT.search(text))


def _redact(text):
    return SECRET_ASSIGNMENT.sub("[已隐藏疑似凭据]", SENSITIVE_TEXT.sub("[已隐藏疑似凭据]", text))


def _forbidden_name(name):
    low = name.lower()
    return (
        low in SECRET_NAMES or low == ".ds_store" or low == ".env" or low.startswith(".env.")
        or low.endswith((".pem", ".key", ".p12", ".pfx", ".pyc", ".swp", ".bak"))
        or low.startswith(("credentials.", "secrets."))
    )


class SkillsService:
    @contextmanager
    def backup_guard(self):
        """Keep draft files and their SQLite metadata at one content version."""
        with self._lock:
            yield

    def __init__(self, store, data_dir, roots=None):
        self.store = store
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.draft_root = self.data_dir / "skills-drafts"
        self.revision_root = self.data_dir / "skills-revisions"
        self.draft_root.mkdir(parents=True, exist_ok=True)
        self.revision_root.mkdir(parents=True, exist_ok=True)
        configured = DEFAULT_ROOTS if roots is None else roots
        self.roots = [Path(p).expanduser().absolute() for p in configured]
        self._allowed_roots = [p.resolve() for p in self.roots] + [self.draft_root.resolve()]
        self._lock = threading.RLock()
        self._hash_cache = {}
        self._catalog = {"items": [], "errors": [], "scanned_at": None, "stats": {}}
        self._packages = {}
        # The initial scan is local and bounded: no network, subprocesses,
        # dependency imports from packages, or recursive symlink traversal.
        self.scan()

    def _allowed(self, path):
        return any(_within(path, root) for root in self._allowed_roots)

    @staticmethod
    def _id(path):
        return "skill-" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:24]

    def _label(self, root):
        if root == self.draft_root:
            return "我沉淀的"
        names = {".agents": "公共技能", ".codex": "Codex", ".claude": "Claude", ".hermes": "Hermes"}
        return names.get(root.parent.name, root.name)

    def _discover(self):
        found, errors = defaultdict(list), []
        for root in self.roots + [self.draft_root]:
            label = self._label(root)
            if not root.is_dir():
                errors.append({"source": label, "message": "来源目录不可用", "path": str(root)})
                continue
            def add(entry):
                try:
                    real = entry.resolve(strict=True)
                    if not self._allowed(real):
                        errors.append({"source": label, "path": str(entry), "message": "软链接目标不在已配置的技能来源内，未读取"})
                        return
                    if not (real / "SKILL.md").is_file():
                        return
                    location = {"label": label, "path": str(entry), "real_path": str(real), "symlink": entry != real}
                    if not any(l["path"] == str(entry) for l in found[real]):
                        found[real].append(location)
                except (OSError, RuntimeError) as exc:
                    errors.append({"source": label, "path": str(entry), "message": "来源无法读取：" + str(exc)})
            for base, dirs, files in os.walk(root, followlinks=False, onerror=lambda exc: errors.append({"source": label, "message": str(exc)})):
                base_path = Path(base)
                dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS and (not d.startswith(".") or d == ".system"))
                # A package inside another package is not counted a second
                # time. Its presence is reported by the resource inspector.
                if "SKILL.md" in files:
                    add(base_path)
                    dirs[:] = []
                    continue
                for d in list(dirs):
                    entry = base_path / d
                    if entry.is_symlink():
                        add(entry)
                        dirs.remove(d)
        return found, errors

    def _file_digest(self, path, data, stat):
        key = (str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        digest = self._hash_cache.get(key)
        if digest is None:
            digest = hashlib.sha256(data).hexdigest()
            self._hash_cache[key] = digest
        return digest

    def _inspect(self, package, blobs=False):
        """Return a deterministic safe-package snapshot; never escape package."""
        files, skipped, contents, total = [], [], {}, 0
        manifest_bytes, display_manifest = b"", b""
        if not self._allowed(package.resolve()):
            raise ValueError("技能包不在已配置来源内")
        for base, dirs, names in os.walk(package, followlinks=False):
            base_path = Path(base)
            kept_dirs = []
            for name in sorted(dirs):
                entry = base_path / name
                rel = entry.relative_to(package).as_posix()
                if name in EXCLUDED_DIRS or name.startswith("."):
                    skipped.append({"path": rel + "/", "reason": "缓存或版本历史目录不打包"})
                elif entry.is_symlink():
                    skipped.append({"path": rel + "/", "reason": "目录软链接不递归展开，请显式提供资源"})
                elif (entry / "SKILL.md").is_file():
                    skipped.append({"path": rel + "/", "reason": "嵌套技能包边界待确认，未计作独立包或自动打包"})
                else:
                    kept_dirs.append(name)
            dirs[:] = kept_dirs
            for name in sorted(names):
                path = base_path / name
                rel = path.relative_to(package).as_posix()
                if _forbidden_name(name):
                    skipped.append({"path": rel, "reason": "凭据、缓存或备份文件不提供或导出"})
                    continue
                try:
                    real = path.resolve(strict=True)
                    if not _within(real, package) or not path.is_file():
                        skipped.append({"path": rel, "reason": "非普通文件或资源链接越过包边界，未读取"})
                        continue
                    stat = path.stat()
                    limit = MAX_MANIFEST_BYTES if rel == "SKILL.md" else MAX_FILE_BYTES
                    if len(files) >= MAX_PACKAGE_FILES or stat.st_size > limit or total + stat.st_size > MAX_PACKAGE_BYTES:
                        skipped.append({"path": rel, "reason": "资源超过单次安全检查上限，完整性未确认"})
                        continue
                    # Opening the resolved path avoids following a replacement
                    # link silently; re-check before and after this read.
                    data = real.read_bytes()
                    if len(data) > limit or path.resolve() != real or path.stat().st_mtime_ns != stat.st_mtime_ns:
                        skipped.append({"path": rel, "reason": "文件在检查期间变化，请重新检查"})
                        continue
                    total += len(data)
                    if rel == "SKILL.md":
                        manifest_bytes = data
                    if _sensitive(data):
                        skipped.append({"path": rel, "reason": "检测到疑似实际凭据，未提供原文件或打包", "sha256": hashlib.sha256(data).hexdigest()})
                        if rel == "SKILL.md":
                            display_manifest = _redact(data.decode("utf-8", errors="replace")).encode("utf-8")
                        continue
                    digest = self._file_digest(real, data, stat)
                    kind = "manifest" if rel == "SKILL.md" else ("script" if path.suffix.lower() in (".py", ".js", ".ts", ".sh", ".ps1") else "resource")
                    files.append({"path": rel, "size": len(data), "sha256": digest, "kind": kind, "symlink": path.is_symlink()})
                    if blobs or rel == "SKILL.md":
                        contents[rel] = data
                except (OSError, RuntimeError) as exc:
                    skipped.append({"path": rel, "reason": "读取失败：" + str(exc)})
        files.sort(key=lambda f: f["path"])
        skipped.sort(key=lambda f: f["path"])
        fingerprint_data = {"policy": "safe-package-v1", "files": [(f["path"], f["sha256"]) for f in files], "omitted": skipped}
        fingerprint = hashlib.sha256(json.dumps(fingerprint_data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        text = contents.get("SKILL.md", display_manifest).decode("utf-8", errors="replace")
        meta, issues = self._manifest(text)
        refs, external = self._references(text, package, {f["path"] for f in files})
        for ref in refs:
            issues.append({"level": "warning", "code": "missing_reference", "path": ref, "message": "原文引用的资源未在安全包中找到：" + ref})
        for omission in skipped:
            issues.append({"level": "warning", "code": "omitted_resource", "path": omission["path"], "message": omission["reason"]})
        if not text:
            issues.append({"level": "error", "code": "manifest_unreadable", "message": "SKILL.md 无法安全读取"})
        complete = bool(text) and not refs and not any(
            not (s["reason"].startswith("缓存") or s["reason"].startswith("凭据、缓存")) for s in skipped
        )
        checks = {
            "status": "invalid" if any(i["level"] == "error" for i in issues) else ("warning" if issues else "valid"),
            "issues": issues, "complete": complete, "missing_references": refs,
            "external_dependencies": external, "omitted": skipped, "executed": False, "checked_at": _now(),
        }
        return {"files": files, "fingerprint": fingerprint, "manifest_fingerprint": hashlib.sha256(manifest_bytes).hexdigest(),
                "body": _redact(text), "manifest": meta, "checks": checks, "blobs": contents}

    @staticmethod
    def _manifest(text):
        issues, meta = [], {}
        match = re.match(r"\A\ufeff?---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", text, re.S)
        if not match:
            issues.append({"level": "error", "code": "frontmatter_missing", "message": "未找到标准 YAML frontmatter；仍可查看原文"})
        else:
            try:
                loaded = yaml.safe_load(match.group(1))
                if isinstance(loaded, dict):
                    meta = loaded
                else:
                    issues.append({"level": "error", "code": "frontmatter_type", "message": "frontmatter 必须是字段对象"})
            except yaml.YAMLError:
                issues.append({"level": "error", "code": "frontmatter_invalid", "message": "YAML frontmatter 格式不正确；未自动重写"})
                # Some existing files have an unquoted colon in description.
                # Recover scalar display fields only; keep the structural
                # error, and never infer executable metadata or rewrite files.
                for field in ("name", "description", "version"):
                    recovered = re.search(r"(?m)^" + field + r":\s*(.+?)\s*$", match.group(1))
                    if recovered:
                        value = recovered.group(1).strip()
                        if not value.startswith(("[", "{", "|", ">")):
                            meta[field] = value.strip("\"'")[:10000]
        for field in ("name", "description"):
            if not isinstance(meta.get(field), str) or not meta.get(field, "").strip():
                issues.append({"level": "error", "code": field + "_missing", "message": "缺少明确的 " + field + " 字段"})
        name = meta.get("name")
        if isinstance(name, str) and (len(name) > 64 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)):
            issues.append({"level": "warning", "code": "legacy_name", "message": "技术名称不符合小写字母、数字及单连字符格式；保留原文，跨工具使用前请核对"})
        return meta, issues

    @staticmethod
    def _references(text, package, available):
        candidates = re.findall(r"\[[^\]]*\]\(([^)]+)\)", text)
        candidates += re.findall(r"`((?:scripts|references|templates|assets|examples)/[^`\n]+|(?:/|~/)[^`\n]+)`", text)
        missing, external = set(), set()
        for raw in candidates:
            candidate = raw.strip().split(' "', 1)[0].strip("<>")
            if not candidate or candidate.startswith(("#", "mailto:", "data:", "javascript:")):
                continue
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", candidate):
                continue
            candidate = candidate.split("#", 1)[0].split("?", 1)[0]
            if any(c in candidate for c in ("*", "{", "}", "$", "\n")):
                continue
            if candidate.startswith(("/", "~/")) or ".." in PurePosixPath(candidate).parts:
                external.add(candidate)
                continue
            if " " in candidate or not candidate or candidate.endswith("/"):
                continue
            normalized = PurePosixPath(candidate).as_posix().removeprefix("./")
            if normalized not in available and not (package / normalized).is_dir():
                missing.add(normalized)
        return sorted(missing), sorted(external)

    @staticmethod
    def _section(body, headings):
        for match in re.finditer(r"(?m)^#{1,4}\s+(.+?)\s*$", body):
            title = match.group(1).strip().lower()
            if not any(h in title for h in headings):
                continue
            rest = body[match.end():]
            end = re.search(r"(?m)^#{1,4}\s+", rest)
            section = rest[:end.start()] if end else rest
            return _text_list(section.strip())[:30]
        return []

    def _decorate(self, base, snapshot):
        item = dict(base)
        meta = self.store.get("skills.meta", {}).get(item["id"], {})
        manifest = snapshot["manifest"]
        technical_name = _redact(_scalar(manifest.get("name"), Path(base["real_path"]).name))
        item.update({
            "name": technical_name, "display_name": meta.get("display_name") or technical_name,
            "description": _redact(_scalar(manifest.get("description"), "原 Skill 未明确说明用途")),
            "category": meta.get("category", "未分类"), "tags": meta.get("tags", []),
            "scenarios": meta.get("scenarios", []), "notes": meta.get("notes", ""),
            "version": _scalar(manifest.get("version")) or snapshot["fingerprint"][:12],
            "declared_version": _scalar(manifest.get("version")) or None,
            "fingerprint": snapshot["fingerprint"], "manifest_fingerprint": snapshot["manifest_fingerprint"],
            "revision_id": "rev-" + item["id"][6:] + "-" + snapshot["fingerprint"][:16],
            "starred": bool(meta.get("starred", False)), "archived": bool(meta.get("archived", False)),
            "pinned": bool(meta.get("pinned", False)),
            "manifest_path": str(Path(base["real_path"]) / "SKILL.md") if any(f["path"] == "SKILL.md" for f in snapshot["files"]) else None,
            "registered": bool(meta.get("registered", False)), "check_status": snapshot["checks"]["status"],
            "package_complete": snapshot["checks"]["complete"], "updated_at": _now(),
        })
        records = self.store.get("skills.validations", {}).get(item["id"], [])
        matching = [r for r in records if r.get("fingerprint") == item["fingerprint"]]
        if matching and matching[-1]["result"] == "success":
            status = "verified"
        elif matching and matching[-1]["result"] == "failure":
            status = "failed"
        elif any(r.get("result") == "success" for r in records):
            status = "outdated"
        else:
            status = "unverified"
        item["validation_status"] = status
        item["current_revision_id"] = item["revision_id"]
        item["task_id"] = meta.get("task_id")
        return item

    def _save_catalog(self):
        self.store.set("skills.catalog", self._catalog)

    def _recount(self):
        names = defaultdict(list)
        items = self._catalog["items"]
        for item in items:
            names[item["name"]].append(item)
        for group in names.values():
            for item in group:
                item["same_name_count"] = len(group)
                item["same_name_different_content"] = len({i["fingerprint"] for i in group}) > 1
        self._catalog["stats"].update({
            "packages": len(items), "physical_packages": len(items),
            "source_packages": sum(not i["draft"] for i in items),
            "linked_locations": sum(l["symlink"] for i in items for l in i["locations"]),
            "same_name_groups": sum(len(g) > 1 for g in names.values()),
            "different_content_groups": sum(len({i["fingerprint"] for i in g}) > 1 for g in names.values()),
            "drafts": sum(i["draft"] and not i["registered"] for i in items),
            "registered": sum(i["registered"] for i in items),
            "verified": sum(i["validation_status"] == "verified" for i in items),
            "incomplete": sum(not i["package_complete"] for i in items),
        })

    def scan(self):
        with self._lock:
            found, errors = self._discover()
            items, packages = [], {}
            for real, locations in sorted(found.items(), key=lambda p: str(p[0])):
                package_id = self._id(real)
                base = {"id": package_id, "source": locations[0]["label"], "locations": locations,
                        "real_path": str(real), "draft": _within(real, self.draft_root.resolve()),
                        "read_only": not _within(real, self.draft_root.resolve())}
                try:
                    snapshot = self._inspect(real)
                    item = self._decorate(base, snapshot)
                    items.append(item)
                    packages[package_id] = base
                except (OSError, ValueError, RuntimeError) as exc:
                    errors.append({"source": base["source"], "path": str(real), "message": str(exc)})
            names = defaultdict(list)
            for item in items:
                names[item["name"]].append(item)
            for group in names.values():
                for item in group:
                    item["same_name_count"] = len(group)
                    item["same_name_different_content"] = len({i["fingerprint"] for i in group}) > 1
            stats = {"packages": len(items), "source_packages": sum(not i["draft"] for i in items),
                     "physical_packages": len(items), "linked_locations": sum(l["symlink"] for i in items for l in i["locations"]),
                     "same_name_groups": sum(len(g) > 1 for g in names.values()),
                     "different_content_groups": sum(len({i["fingerprint"] for i in g}) > 1 for g in names.values()),
                     "drafts": sum(i["draft"] for i in items), "registered": sum(i["registered"] for i in items),
                     "verified": sum(i["validation_status"] == "verified" for i in items),
                     "incomplete": sum(not i["package_complete"] for i in items), "roots": len(self.roots)}
            self._packages = packages
            self._catalog = {"items": items, "errors": errors, "scanned_at": _now(), "stats": stats}
            self._recount()
            self._save_catalog()
            return self.list()

    def list(self):
        with self._lock:
            return json.loads(json.dumps(self._catalog, ensure_ascii=False))

    def _get(self, package_id):
        if package_id not in self._packages:
            raise KeyError("找不到该 Skill，请重新扫描来源")
        base = self._packages[package_id]
        package = Path(base["real_path"])
        if not package.is_dir():
            raise ValueError("技能来源当前不可用，请重新扫描")
        return base, package

    def _refresh(self, package_id, with_blobs=False):
        base, package = self._get(package_id)
        snapshot = self._inspect(package, blobs=with_blobs)
        item = self._decorate(base, snapshot)
        old = next((i for i in self._catalog["items"] if i["id"] == package_id), {})
        for field in ("same_name_count", "same_name_different_content"):
            item[field] = old.get(field, 1 if field == "same_name_count" else False)
        self._catalog["items"] = [item if i["id"] == package_id else i for i in self._catalog["items"]]
        self._recount()
        self._save_catalog()
        return item, snapshot

    def detail(self, package_id):
        with self._lock:
            item, snap = self._refresh(package_id)
            body, manifest = snap["body"], snap["manifest"]
            records = self.store.get("skills.validations", {}).get(package_id, [])
            result = dict(item)
            result.update({"body": body, "files": snap["files"], "checks": snap["checks"],
                           "validations": [dict(r, current=r.get("fingerprint") == item["fingerprint"]) for r in records],
                           "inputs": _text_list(manifest.get("inputs")) or self._section(body, ("输入", "input")),
                           "outputs": _text_list(manifest.get("outputs")) or self._section(body, ("输出", "产物", "output")),
                           "workflow": _text_list(manifest.get("workflow")) or self._section(body, ("执行步骤", "workflow", "步骤")),
                           "dependencies": _text_list(manifest.get("dependencies")) or self._section(body, ("依赖", "运行前提", "技术栈", "环境要求", "工具要求", "dependency", "dependencies", "prerequisite", "requirements")),
                           "environment_evidence": {"files_found": True, "ai_discoverable": "unknown", "runtime_support": "unknown", "session_loaded": "unknown"},
                           "source_task_id": item.get("task_id")})
            return result

    def copy_target(self, package_id):
        """Resolve an indexed, currently readable entry; never install or run it."""
        with self._lock:
            try:
                item, snapshot = self._refresh(package_id)
                package = Path(item["real_path"]).resolve(strict=True)
                manifest = package / "SKILL.md"
                target = manifest.resolve(strict=True)
                if not self._allowed(package) or not _within(target, package) or not target.is_file():
                    raise ValueError("技能入口不在当前安全包内")
            except (OSError, RuntimeError) as exc:
                raise ValueError("技能入口当前不可用，请重新扫描来源") from exc
            if not any(f["path"] == "SKILL.md" for f in snapshot["files"]):
                raise ValueError("技能入口无法安全读取，请查看检查结果")
            return {"id": package_id, "manifest_path": str(manifest), "package_path": str(package)}

    def meta(self, package_id, payload):
        with self._lock:
            self._get(package_id)
            if not isinstance(payload, dict):
                raise ValueError("元数据必须是对象")
            changes = {}
            for key in ("starred", "archived", "pinned"):
                if key in payload:
                    if not isinstance(payload[key], bool):
                        raise ValueError(key + " 必须为布尔值")
                    changes[key] = payload[key]
            for key in ("display_name", "category", "notes"):
                if key in payload:
                    if not isinstance(payload[key], str) or len(payload[key]) > 10000:
                        raise ValueError(key + " 必须为长度合理的文字")
                    changes[key] = payload[key].strip()
            for key in ("tags", "scenarios"):
                if key in payload:
                    value = payload[key]
                    if isinstance(value, str):
                        value = re.split(r"[,，\n]", value)
                    if not isinstance(value, list) or any(not isinstance(v, str) for v in value) or len(value) > 40:
                        raise ValueError(key + " 必须为文字列表")
                    changes[key] = list(dict.fromkeys(v.strip()[:200] for v in value if v.strip()))
            self._update_meta(package_id, changes)
            return self.detail(package_id)

    def _update_meta(self, package_id, changes):
        def update(all_meta):
            all_meta = all_meta or {}
            all_meta[package_id] = dict(all_meta.get(package_id, {}), **changes)
            return all_meta
        self.store.update("skills.meta", update, default={})

    @staticmethod
    def _draft_text(payload, previous=None):
        name = payload.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
            raise ValueError("技术名称请使用小写字母、数字和连字符，最多 64 字符")
        description = payload.get("description", "")
        if not isinstance(description, str) or len(description) > 10000:
            raise ValueError("用途描述必须是文字")
        body = payload.get("body", "")
        if not isinstance(body, str) or len(body.encode("utf-8")) > MAX_MANIFEST_BYTES:
            raise ValueError("草稿正文过长或格式不正确")
        if body.lstrip().startswith("---"):
            # Preserve user supplied frontmatter, including AI-specific fields.
            # Structural validation remains a separate, explicit operation.
            text = body
        else:
            front = {"name": name, "description": description}
            if payload.get("version"):
                front["version"] = _scalar(payload["version"])
            for key in ("inputs", "outputs", "dependencies"):
                if key in payload:
                    front[key] = _text_list(payload[key])
            if not body.strip():
                chunks = ["# " + (payload.get("display_name") or name)]
                for key, heading in (("inputs", "输入"), ("outputs", "输出"), ("workflow", "执行步骤"), ("dependencies", "依赖与运行前提")):
                    value = "\n".join(_text_list(payload.get(key)))
                    chunks += ["## " + heading, value or "待补充"]
                body = "\n\n".join(chunks) + "\n"
            text = "---\n" + yaml.safe_dump(front, allow_unicode=True, sort_keys=False) + "---\n\n" + body
        if _sensitive(text.encode("utf-8")):
            raise ValueError("草稿包含疑似实际凭据，请改为环境变量或占位符")
        return text

    @staticmethod
    def _resources(payload):
        resources = payload.get("resources", [])
        if not isinstance(resources, list):
            raise ValueError("resources 必须是 filename/text 对象列表")
        result, total = {}, 0
        for resource in resources:
            if not isinstance(resource, dict):
                raise ValueError("每个资源必须包含 filename 与 text")
            filename, text = resource.get("filename"), resource.get("text")
            if not isinstance(filename, str) or not isinstance(text, str):
                raise ValueError("资源 filename 与 text 必须是文字")
            path = PurePosixPath(filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in filename or not filename or filename.endswith("/")
                    or not path.parts or ":" in filename
                    or any(p.startswith(".") or p in EXCLUDED_DIRS or _forbidden_name(p) for p in path.parts)
                    or path.as_posix() == "SKILL.md"):
                raise ValueError("资源文件名越界、属于保留文件或包含敏感文件名")
            data = text.encode("utf-8")
            total += len(data)
            if _sensitive(data) or len(data) > MAX_FILE_BYTES or total > MAX_PACKAGE_BYTES or len(result) >= MAX_PACKAGE_FILES:
                raise ValueError("资源包含疑似凭据或超出包大小限制")
            if any(path.as_posix().startswith(other + "/") or other.startswith(path.as_posix() + "/") for other in result):
                raise ValueError("资源文件名与目录名相互冲突")
            result[path.as_posix()] = data
        return result

    @staticmethod
    def _structured_edit_text(original, payload):
        """Edit supplied form fields, preserving all unknown YAML metadata.

        An explicitly supplied body is authoritative in edit_draft. This helper
        only runs for a structured form submission that did not include body.
        """
        match = re.match(r"\A\ufeff?---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", original, re.S)
        if not match:
            raise ValueError("草稿格式不规范，请用完整正文编辑模式修复")
        try:
            front = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            raise ValueError("草稿 YAML 不规范，请用完整正文编辑模式修复")
        if not isinstance(front, dict):
            raise ValueError("草稿 frontmatter 必须是字段对象")
        for key in ("name", "description", "version"):
            if key in payload:
                front[key] = payload[key]
        for key in ("inputs", "outputs", "dependencies"):
            if key in payload:
                front[key] = _text_list(payload[key])
        body = original[match.end():].lstrip("\r\n")
        for key, heading, names in (
            ("inputs", "输入", ("输入", "input", "inputs")),
            ("outputs", "输出", ("输出", "产物", "output", "outputs")),
            ("workflow", "执行步骤", ("执行步骤", "工作流程", "workflow")),
            ("dependencies", "依赖与运行前提", ("依赖", "依赖与运行前提", "dependencies", "prerequisites")),
        ):
            if key not in payload:
                continue
            replacement = "## " + heading + "\n\n" + "\n".join("- " + s for s in _text_list(payload[key])) + "\n\n"
            section = None
            for current in re.finditer(r"(?m)^#{1,4}\s+(.+?)\s*$", body):
                if current.group(1).strip().lower() in names:
                    following = re.search(r"(?m)^#{1,4}\s+", body[current.end():])
                    end = current.end() + following.start() if following else len(body)
                    section = (current.start(), end)
                    break
            body = body[:section[0]] + replacement + body[section[1]:] if section else body.rstrip() + "\n\n" + replacement
        return "---\n" + yaml.safe_dump(front, allow_unicode=True, sort_keys=False) + "---\n\n" + body

    def _snapshot(self, package_id, snapshot):
        if not snapshot["checks"]["complete"]:
            return
        target = self.revision_root / package_id / snapshot["fingerprint"]
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".revision-", dir=target.parent))
        try:
            for rel, data in snapshot["blobs"].items():
                out = temporary / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
            (temporary / "WORKBENCH-REVISION.json").write_text(json.dumps({"fingerprint": snapshot["fingerprint"], "created_at": _now(), "files": snapshot["files"]}, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def create_draft(self, payload):
        with self._lock:
            if not isinstance(payload, dict):
                raise ValueError("草稿内容必须是对象")
            text, resources = self._draft_text(payload), self._resources(payload)
            path = self.draft_root / (payload["name"] + "-" + uuid.uuid4().hex[:10])
            temporary = Path(tempfile.mkdtemp(prefix=".draft-", dir=self.draft_root))
            try:
                (temporary / "SKILL.md").write_text(text, encoding="utf-8")
                for rel, data in resources.items():
                    out = temporary / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(data)
                os.replace(temporary, path)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            package_id = self._id(path.resolve())
            self._update_meta(package_id, {"display_name": payload.get("display_name") or payload["name"], "task_id": payload.get("task_id"), "registered": False, "created_at": _now()})
            self.scan()
            return self.detail(package_id)

    def edit_draft(self, package_id, payload):
        with self._lock:
            base, package = self._get(package_id)
            if not base["draft"]:
                raise ValueError("已有来源包只读；请在独立草稿中编辑")
            if not isinstance(payload, dict):
                raise ValueError("草稿内容必须是对象")
            item, old = self._refresh(package_id, with_blobs=True)
            expected = payload.get("fingerprint") or payload.get("expected_fingerprint")
            if expected and expected != item["fingerprint"]:
                raise ValueError("草稿已被修改，请重新载入再保存")
            merged = {"name": item["name"], "description": item["description"], "display_name": item["display_name"]}
            merged.update(payload)
            if "body" not in payload:
                merged["body"] = self._structured_edit_text(old["body"], payload)
            text = self._draft_text(merged)
            resources = self._resources(payload) if "resources" in payload else {r: b for r, b in old["blobs"].items() if r != "SKILL.md"}
            if "resources" in payload and payload.get("resource_mode") == "merge":
                resources = dict({r: b for r, b in old["blobs"].items() if r != "SKILL.md"}, **resources)
                if len(resources) > MAX_PACKAGE_FILES or sum(len(value) for value in resources.values()) > MAX_PACKAGE_BYTES:
                    raise ValueError("资源总量超出技能包限制")
            self._snapshot(package_id, old)
            staging = Path(tempfile.mkdtemp(prefix=".edit-", dir=self.draft_root))
            backup = self.draft_root / (".previous-" + uuid.uuid4().hex)
            try:
                (staging / "SKILL.md").write_text(text, encoding="utf-8")
                for rel, data in resources.items():
                    out = staging / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(data)
                os.replace(package, backup)
                try:
                    os.replace(staging, package)
                except BaseException:
                    os.replace(backup, package)
                    raise
                shutil.rmtree(backup)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
            changes = {k: payload[k] for k in ("display_name", "task_id") if k in payload}
            self._update_meta(package_id, changes)
            return self.detail(package_id)

    def check(self, package_id):
        return self.detail(package_id)

    def register(self, package_id):
        with self._lock:
            base, _ = self._get(package_id)
            if not base["draft"]:
                raise ValueError("已有来源已在索引中，无需登记或改写")
            item, snapshot = self._refresh(package_id, with_blobs=True)
            if snapshot["checks"]["status"] == "invalid" or not snapshot["checks"]["complete"]:
                raise ValueError("请先补齐草稿结构和缺失资源，再登记")
            self._snapshot(package_id, snapshot)
            self._update_meta(package_id, {"registered": True, "registered_at": _now(), "registered_revision_id": item["revision_id"]})
            return self.detail(package_id)

    def validate(self, package_id, payload):
        with self._lock:
            if not isinstance(payload, dict):
                raise ValueError("验证记录必须是对象")
            item, snapshot = self._refresh(package_id, with_blobs=True)
            aliases = {"success": "success", "passed": "success", "通过": "success", "failure": "failure", "failed": "failure", "失败": "failure", "partial": "partial", "部分通过": "partial"}
            result = aliases.get(payload.get("result")) if isinstance(payload.get("result"), str) else None
            if result is None:
                raise ValueError("验证结果请选择 success、failure 或 partial")
            scenario, environment, evidence = (_scalar(payload.get(k)).strip() for k in ("scenario", "environment", "evidence"))
            if not scenario or not environment:
                raise ValueError("请记录验证场景和 AI/设备环境")
            if result == "success" and not evidence:
                raise ValueError("记录成功必须提供实际产物或执行证据")
            if result == "success" and (not snapshot["checks"]["complete"] or snapshot["checks"]["status"] == "invalid"):
                raise ValueError("包结构或完整性未确认，不能标记整包验证成功")
            record = {"id": "validation-" + uuid.uuid4().hex, "revision_id": item["revision_id"], "fingerprint": item["fingerprint"],
                      "scenario": scenario[:2000], "environment": environment[:2000], "result": result,
                      "evidence": _redact(evidence[:20000]), "at": _now(), "source": "manual", "manual": True}
            def update(records):
                records = records or {}
                records.setdefault(package_id, []).append(record)
                return records
            self.store.update("skills.validations", update, default={})
            if item["draft"]:
                self._snapshot(package_id, snapshot)
            return self.detail(package_id)

    def prompt(self, package_id, task=None, target=None):
        detail = self.detail(package_id)
        task_name = _scalar(task.get("title")) if isinstance(task, dict) else _scalar(task)
        task_context = _scalar(task.get("summary") or task.get("brief")) if isinstance(task, dict) else ""
        target_name = _scalar(target.get("name")) if isinstance(target, dict) else _scalar(target)
        lines = ["请使用技能「" + detail["display_name"] + "」处理以下任务。", "内容版本：" + detail["fingerprint"],
                 "目标 AI/环境：" + (target_name or "请填写实际 AI 与设备"), "任务：" + (task_name or "请填写要完成的任务")]
        if task_context:
            lines += ["任务背景：" + task_context]
        lines += ["\n使用准备：", "当前未确认目标 AI 可以读取本机技能目录。请先下载此版本完整包并附加给目标 AI，或确认下列入口在目标设备可访问："]
        lines += ["- " + l["label"] + "：" + l["path"] for l in detail["locations"]]
        lines += ["请先阅读包内 SKILL.md，核对输入、依赖与适用条件；缺少条件时明确说明，不要声称已加载或已执行。",
                  "\n必要输入：", "\n".join("- " + s for s in detail["inputs"]) or "原 Skill 未明确说明，请补充本次输入。",
                  "\n期望输出：", "\n".join("- " + s for s in detail["outputs"]) or "原 Skill 未明确说明，请确认本次交付物。",
                  "\n依赖与前提：", "\n".join("- " + s for s in detail["dependencies"]) or "原 Skill 未明确说明，请在执行前核对。"]
        if not detail["package_complete"]:
            lines.append("注意：本包完整性尚未确认，先补齐详情页报告的缺失资源。")
        return "\n".join(lines)

    def export(self, package_id):
        with self._lock:
            item, snapshot = self._refresh(package_id, with_blobs=True)
            if "SKILL.md" not in snapshot["blobs"]:
                raise ValueError("SKILL.md 无法安全读取，不能导出技能包")
            slug = re.sub(r"[^A-Za-z0-9_-]+", "-", item["name"]).strip("-")[:64] or "skill"
            # A valid Agent Skills package unpacks into a directory matching
            # its technical name. The download filename carries the revision.
            folder = slug
            download_name = slug + "-" + item["fingerprint"][:12] + ".zip"
            dependencies = _text_list(snapshot["manifest"].get("dependencies")) or self._section(
                snapshot["body"], ("依赖", "运行前提", "技术栈", "环境要求", "工具要求", "dependency", "dependencies", "prerequisite", "requirements"))
            report = {"skill_id": package_id, "revision_id": item["revision_id"], "fingerprint": item["fingerprint"],
                      "complete": snapshot["checks"]["complete"], "exported_at": _now(), "files": snapshot["files"],
                      "checks": snapshot["checks"], "dependencies": dependencies,
                      "directory_name_matches_manifest": folder == item["name"],
                      "notice": "导出不是安装或运行。原始许可文件随资源保留；外部工具、账号与未打包依赖须另行确认。"}
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for relative, data in sorted(snapshot["blobs"].items()):
                    archive.writestr(folder + "/" + relative, data)
                archive.writestr(folder + "/WORKBENCH-EXPORT.json", json.dumps(report, ensure_ascii=False, indent=2))
            return download_name, output.getvalue()
