import io
import json
import zipfile
from pathlib import Path

import pytest

from workbench.db import Store
from workbench.skills import SkillsService


MANIFEST = "---\nname: task-sync\ndescription: 同步任务面板\n---\n\n# 使用\n\n## 输入\n- 任务资料\n\n## 输出\n- 最新任务面板\n"


def package(root, folder="sync", body=MANIFEST):
    path = root / folder
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(body, encoding="utf-8")
    return path


def service(tmp_path, roots):
    data = tmp_path / "data"
    return SkillsService(Store(data / "workbench.sqlite3"), data, roots=roots)


def test_realpath_identity_aliases_same_names_and_conservative_nested_boundary(tmp_path):
    shared, claude = tmp_path / "shared", tmp_path / "claude"
    source = package(shared)
    claude.mkdir()
    (claude / "alias").symlink_to(source, target_is_directory=True)
    other = package(claude, "different-copy", MANIFEST.replace("最新任务面板", "另一份产物"))
    nested = package(source, "nested")
    outside = package(tmp_path / "outside")
    (claude / "unapproved").symlink_to(outside, target_is_directory=True)
    svc = service(tmp_path, [shared, claude])
    result = svc.list()
    assert len(result["items"]) == 2
    item = next(i for i in result["items"] if i["real_path"] == str(source.resolve()))
    assert len(item["locations"]) == 2
    assert sum(l["symlink"] for l in item["locations"]) == 1
    assert all(i["same_name_different_content"] for i in result["items"])
    assert result["stats"]["linked_locations"] == 1
    assert any("已配置" in e["message"] for e in result["errors"])
    assert any("嵌套" in i["message"] for i in svc.detail(item["id"])["checks"]["issues"])
    assert not any(i["real_path"] == str(nested) for i in result["items"])
    stable = item["id"]
    (claude / "alias").unlink()
    svc.scan()
    assert any(i["id"] == stable for i in svc.list()["items"])
    assert other.exists()


def test_bad_manifest_and_missing_source_do_not_block_other_packages_or_execute_scripts(tmp_path):
    root = tmp_path / "skills"
    good = package(root)
    package(root, "bad", "---\nname: [bad\n---\n# 可读取的原文")
    package(root, "legacy", "# 旧格式也保留")
    script = good / "scripts" / "never_execute.py"
    script.parent.mkdir()
    marker = tmp_path / "EXECUTED"
    script.write_text("from pathlib import Path\nPath(%r).write_text('bad')\n" % str(marker))
    svc = service(tmp_path, [root, tmp_path / "missing"])
    result = svc.list()
    assert len(result["items"]) == 3
    assert sum(i["check_status"] == "invalid" for i in result["items"]) == 2
    bad = next(i for i in result["items"] if i["name"] == "bad")
    assert "可读取的原文" in svc.detail(bad["id"])["body"]
    assert result["errors"]
    assert not marker.exists()


def test_resource_only_change_invalidates_validation_and_keeps_history(tmp_path):
    root = tmp_path / "skills"
    pkg = package(root, body=MANIFEST + "\n使用 [模板](templates/board.html)。\n")
    template = pkg / "templates/board.html"
    template.parent.mkdir()
    template.write_text("<p>before</p>")
    svc = service(tmp_path, [root])
    item = svc.list()["items"][0]
    with pytest.raises(ValueError, match="证据"):
        svc.validate(item["id"], {"result": "success", "scenario": "同步", "environment": "本机 Codex"})
    record = {"result": "success", "scenario": "同步", "environment": "本机 Codex", "evidence": "已实际生成目标面板，人工检查通过"}
    verified = svc.validate(item["id"], record)
    assert verified["validation_status"] == "verified"
    template.write_text("<p>after!</p>")
    current = svc.detail(item["id"])
    assert current["fingerprint"] != item["fingerprint"]
    assert current["manifest_fingerprint"] == item["manifest_fingerprint"]
    assert current["revision_id"] != item["revision_id"]
    assert current["validation_status"] == "outdated"
    assert current["validations"][0]["current"] is False
    assert current["validations"][0]["manual"] is True
    reopened = SkillsService(svc.store, svc.data_dir, roots=[root])
    assert reopened.detail(item["id"])["validation_status"] == "outdated"


def test_metadata_does_not_change_source_and_persists(tmp_path):
    root = tmp_path / "skills"
    pkg = package(root)
    original = (pkg / "SKILL.md").read_bytes()
    svc = service(tmp_path, [root])
    package_id = svc.list()["items"][0]["id"]
    item = svc.meta(package_id, {"display_name": "任务同步", "starred": True, "tags": "看板,任务,看板", "category": "办公", "scenarios": ["每日任务更新"]})
    assert item["display_name"] == "任务同步"
    assert item["tags"] == ["看板", "任务"]
    assert item["scenarios"] == ["每日任务更新"]
    assert (pkg / "SKILL.md").read_bytes() == original
    reopened = SkillsService(svc.store, svc.data_dir, roots=[root])
    assert reopened.list()["items"][0]["starred"] is True
    with pytest.raises(ValueError, match="只读"):
        svc.edit_draft(package_id, {"body": "不能覆盖"})
    with pytest.raises(KeyError):
        svc.detail("missing-id")


def test_copy_target_uses_real_package_and_pinning_is_metadata_only(tmp_path):
    root, aliases = tmp_path / '源技能', tmp_path / 'aliases'
    pkg = package(root, folder='任务维护')
    aliases.mkdir()
    (aliases / 'entry').symlink_to(pkg, target_is_directory=True)
    before = (pkg / 'SKILL.md').read_bytes()
    svc = service(tmp_path, [root, aliases])
    item = svc.list()['items'][0]
    target = svc.copy_target(item['id'])
    assert target == {'id': item['id'], 'manifest_path': str(pkg.resolve() / 'SKILL.md'), 'package_path': str(pkg.resolve())}
    assert item['manifest_path'] == target['manifest_path']
    assert len(svc.list()['items']) == 1
    svc.meta(item['id'], {'pinned': True, 'starred': True})
    reopened = service(tmp_path, [root, aliases])
    assert reopened.detail(item['id'])['pinned']
    assert (pkg / 'SKILL.md').read_bytes() == before
    with pytest.raises(ValueError, match='布尔值'):
        svc.meta(item['id'], {'pinned': 'true'})
    (pkg / 'SKILL.md').unlink()
    with pytest.raises(ValueError):
        svc.copy_target(item['id'])


def test_copy_target_rechecks_manifest_symlink_boundary_and_credentials(tmp_path):
    root = tmp_path / 'skills'
    pkg = package(root)
    outside = tmp_path / 'outside.md'
    outside.write_text(MANIFEST)
    svc = service(tmp_path, [root])
    skill_id = svc.list()['items'][0]['id']
    (pkg / 'SKILL.md').unlink()
    (pkg / 'SKILL.md').symlink_to(outside)
    with pytest.raises(ValueError):
        svc.copy_target(skill_id)
    (pkg / 'SKILL.md').unlink()
    (pkg / 'SKILL.md').write_text(MANIFEST + '\nAPI_KEY=' + 'a' * 32)
    with pytest.raises(ValueError, match='安全读取'):
        svc.copy_target(skill_id)


def test_resource_upload_merge_keeps_previous_files_and_rejects_stale_editor(tmp_path):
    svc = service(tmp_path, [])
    draft = svc.create_draft({'name': 'resource-skill', 'description': '资源处理', 'workflow': ['执行步骤'], 'resources': [{'filename': 'references/old.md', 'text': '必须保留'}]})
    changed = svc.edit_draft(draft['id'], {'expected_fingerprint': draft['fingerprint'], 'resources': [{'filename': 'scripts/run.py', 'text': 'print("only stored, never run")'}], 'resource_mode': 'merge'})
    paths = {x['path'] for x in changed['files']}
    assert {'references/old.md', 'scripts/run.py', 'SKILL.md'} <= paths
    with pytest.raises(ValueError, match='已被修改'):
        svc.edit_draft(draft['id'], {'expected_fingerprint': draft['fingerprint'], 'description': '旧窗口的改动'})


def test_draft_create_register_edit_and_immutable_revision_evidence(tmp_path):
    svc = service(tmp_path, [])
    draft = svc.create_draft({"name": "my-board", "display_name": "我的看板技能", "description": "生成任务看板", "inputs": ["任务文件"], "outputs": ["HTML 面板"], "workflow": ["读任务", "套模板"], "dependencies": ["Python 3"], "task_id": "task-1", "resources": [{"filename": "templates/board.html", "text": "<p>version one</p>"}]})
    package_id = draft["id"]
    assert draft["draft"] and not draft["registered"]
    assert draft["source_task_id"] == "task-1"
    assert draft["inputs"] == ["任务文件"]
    assert draft["outputs"] == ["HTML 面板"]
    assert draft["workflow"] == ["读任务", "套模板"]
    assert draft["checks"]["executed"] is False
    registered = svc.register(package_id)
    assert registered["registered"] and registered["validation_status"] == "unverified"
    assert svc.list()["stats"]["registered"] == 1
    assert svc.list()["stats"]["drafts"] == 0
    svc.validate(package_id, {"scenario": "第二次生成", "environment": "Mac / Codex", "result": "success", "evidence": "实际生成文件"})
    assert svc.list()["stats"]["verified"] == 1
    old_hash = draft["fingerprint"]
    changed = svc.edit_draft(package_id, {"fingerprint": old_hash, "resources": [{"filename": "templates/board.html", "text": "<p>version two</p>"}]})
    assert changed["id"] == package_id
    assert changed["fingerprint"] != old_hash
    assert changed["validation_status"] == "outdated"
    assert changed["workflow"] == ["读任务", "套模板"]
    assert svc.list()["stats"]["verified"] == 0
    old_snapshot = svc.revision_root / package_id / old_hash
    assert (old_snapshot / "templates/board.html").read_text() == "<p>version one</p>"
    with pytest.raises(ValueError, match="已被修改"):
        svc.edit_draft(package_id, {"fingerprint": old_hash, "body": "旧表单覆盖"})
    text = svc.prompt(package_id, {"title": "本周看板", "summary": "整理当前待办"}, "另一台电脑的 Claude")
    assert "本周看板" in text and changed["fingerprint"] in text
    assert "下载" in text and "附加" in text and "未确认" in text


@pytest.mark.parametrize("filename", ["../outside.txt", "/tmp/outside.txt", ".env", "scripts/credentials.json", "scripts/../../outside.txt"])
def test_draft_resources_never_read_or_write_arbitrary_paths(tmp_path, filename):
    svc = service(tmp_path, [])
    with pytest.raises(ValueError):
        svc.create_draft({"name": "safe-draft", "description": "安全草稿", "resources": [{"filename": filename, "text": "text"}]})
    assert svc.list()["items"] == []
    assert not (tmp_path / "outside.txt").exists()


def test_export_preserves_resources_and_license_excludes_credentials_and_external_links(tmp_path):
    root = tmp_path / "skills"
    pkg = package(root, body=MANIFEST + "\n[模板](templates/board.html) [外部工具](../shared/tool.py)\n")
    (pkg / "templates").mkdir()
    (pkg / "templates/board.html").write_text("<h1>真实模板</h1>")
    (pkg / "LICENSE").write_text("MIT License\n")
    (pkg / ".env").write_text("PASSWORD=must-not-leave-this-file")
    (pkg / ".git").mkdir()
    (pkg / ".git/private-history").write_text("not exported")
    (pkg / "cache").mkdir()
    (pkg / "cache/token.txt").write_text("not exported")
    outside = tmp_path / "private.txt"
    outside.write_text("do not read or export")
    (pkg / "escape.txt").symlink_to(outside)
    (pkg / "credentials.json").write_text('{"token":"not exported"}')
    svc = service(tmp_path, [root])
    item = svc.list()["items"][0]
    before = {str(p): p.read_bytes() for p in pkg.rglob("*") if p.is_file() and not p.is_symlink()}
    filename, data = svc.export(item["id"])
    assert filename.endswith(".zip")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert {n.split("/", 1)[0] for n in names} == {"task-sync"}
        assert any(n.endswith("/SKILL.md") for n in names)
        assert any(n.endswith("/templates/board.html") for n in names)
        assert any(n.endswith("/LICENSE") for n in names)
        assert not any(n.endswith(("/.env", "/credentials.json", "/escape.txt")) or "/.git/" in n or "/cache/" in n for n in names)
        report = json.loads(archive.read(next(n for n in names if n.endswith("/WORKBENCH-EXPORT.json"))))
        assert "../shared/tool.py" in report["checks"]["external_dependencies"]
        assert report["complete"] is False
        assert any("越过" in s["reason"] for s in report["checks"]["omitted"])
    after = {str(p): p.read_bytes() for p in pkg.rglob("*") if p.is_file() and not p.is_symlink()}
    assert before == after


def test_missing_references_block_draft_registration_and_secret_resource_is_rejected(tmp_path):
    svc = service(tmp_path, [])
    draft = svc.create_draft({"name": "missing-tools", "description": "检查缺失资源", "body": "# 方法\n请运行 `scripts/missing.py`。"})
    assert draft["checks"]["missing_references"] == ["scripts/missing.py"]
    with pytest.raises(ValueError, match="资源"):
        svc.register(draft["id"])
    with pytest.raises(ValueError, match="凭据"):
        svc.create_draft({"name": "secret-package", "description": "不应保存凭据", "resources": [{"filename": "config.txt", "text": "sk-" + "a" * 40}]})


def test_structured_edit_changes_fields_raw_edit_preserves_ai_metadata(tmp_path):
    svc = service(tmp_path, [])
    raw = "---\nname: rich-draft\ndescription: 原用途\nmetadata:\n  hermes:\n    tags: [Research]\n---\n\n# 做法\n\n## 输入\n- 原输入\n"
    draft = svc.create_draft({"name": "rich-draft", "description": "表单默认值", "body": raw})
    changed = svc.edit_draft(draft["id"], {"description": "新用途", "inputs": ["新输入"], "workflow": ["检查", "生成"]})
    assert changed["description"] == "新用途"
    assert changed["inputs"] == ["新输入"]
    assert "hermes:" in changed["body"] and "Research" in changed["body"]
    assert "原输入" not in changed["body"]
    assert "## 执行步骤" in changed["body"]
    assert changed["workflow"] == ["检查", "生成"]
    preserved = svc.edit_draft(draft["id"], {"description": "仅改用途"})
    assert preserved["workflow"] == ["检查", "生成"]
    raw_changed = svc.edit_draft(draft["id"], {"description": "陈旧表单不能覆盖正文", "body": raw.replace("原用途", "正文中的用途")})
    assert raw_changed["description"] == "正文中的用途"
    assert "hermes:" in raw_changed["body"]


def test_legacy_yaml_remains_searchable_and_sensitive_manifest_has_safe_preview_only(tmp_path):
    root = tmp_path / "skills"
    package(root, "legacy-colon", "---\nname: legacy-colon\ndescription: 业务场景: 任务同步\n---\n# 原文\n")
    key = "sk-" + "z" * 40
    package(root, "sensitive", "---\nname: sensitive-example\ndescription: 包含历史凭据的旧技能\n---\n# 原文\nAPI 示例：`" + key + "`\n")
    svc = service(tmp_path, [root])
    legacy = next(i for i in svc.list()["items"] if i["name"] == "legacy-colon")
    assert "任务同步" in legacy["description"]
    assert legacy["check_status"] == "invalid"
    sensitive = next(i for i in svc.list()["items"] if i["name"] == "sensitive-example")
    detail = svc.detail(sensitive["id"])
    assert "# 原文" in detail["body"] and key not in detail["body"]
    assert not detail["package_complete"]
    with pytest.raises(ValueError, match="安全读取"):
        svc.export(sensitive["id"])
