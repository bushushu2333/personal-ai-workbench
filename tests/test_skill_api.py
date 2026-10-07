"""Real SkillsService through FastAPI, with isolated sources and data only."""

import io
import json
import shutil
import zipfile

from fastapi.testclient import TestClient

from server import create_app
from workbench.skills import SkillsService


HEADERS = {"X-Workbench": "1"}
BASE_URL = "http://127.0.0.1:4186"


class SourcesStub:
    def __init__(self, store, data_dir):
        pass

    def tasks(self):
        return {"items": [{"id": "task-acceptance", "title": "制作每周任务看板", "status": "progress", "summary": "从已确认任务生成可复用面板"}], "source_status": "ok"}

    def discover(self):
        return {"items": [], "status": "unconfigured"}

    def devices(self):
        return {"items": [{"id": "test-mac", "name": "验收设备"}]}

    def agents(self):
        return {"items": [{"id": "test-ai", "name": "验收 AI", "activities": []}]}


def make_app(data, root):
    return create_app(data, background=False, sources_factory=SourcesStub,
                      skills_factory=lambda store, directory: SkillsService(store, directory, roots=[root]))


def existing_package(root):
    package = root / "existing-skill"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text("---\nname: existing-skill\ndescription: 已有只读测试技能\n---\n\n# 方法\n只读展示。\n", encoding="utf-8")
    return package


def mutation(client, method, url, payload=None, expected=200):
    response = getattr(client, method)(url, headers=HEADERS, json=payload)
    assert response.status_code == expected, response.text
    if expected == 200:
        assert response.json()["ok"] is True
    return response


def test_real_skill_lifecycle_zip_relations_and_backup_restore(tmp_path):
    root, data = tmp_path / "sources", tmp_path / "data"
    source = existing_package(root)
    source_before = (source / "SKILL.md").read_bytes()
    with TestClient(make_app(data, root), base_url=BASE_URL) as client:
        bootstrap = client.get("/api/bootstrap").json()
        assert len(bootstrap["skills"]["items"]) == 1
        assert bootstrap["tasks"]["items"][0]["id"] == "task-acceptance"
        created = mutation(client, "post", "/api/skills/drafts", {
            "name": "weekly-board", "display_name": "每周任务看板", "description": "从成功任务沉淀的面板方法",
            "inputs": ["确认过的任务"], "outputs": ["单文件任务看板"], "workflow": ["整理任务", "应用模板"],
            "dependencies": ["支持 HTML 输出的 AI"], "task_id": "task-acceptance",
            "resources": [{"filename": "templates/board.html", "text": "<main>first template</main>"}],
        }).json()
        skill_id = created["id"]
        assert created["skill"]["id"] == skill_id
        assert created["skill"]["source_task_id"] == "task-acceptance"
        assert created["skill"]["draft"] and not created["skill"]["registered"]

        base_url = "/api/skills/" + skill_id
        edited = mutation(client, "put", "/api/skills/drafts/" + skill_id, {
            "fingerprint": created["skill"]["fingerprint"], "description": "已整理好的每周任务面板方法",
            "inputs": ["确认任务", "本周日期"], "workflow": ["核对任务", "填入模板", "人工检查"],
        }).json()["skill"]
        assert edited["description"] == "已整理好的每周任务面板方法"
        assert edited["inputs"] == ["确认任务", "本周日期"]
        assert edited["workflow"] == ["核对任务", "填入模板", "人工检查"]
        checked = mutation(client, "post", base_url + "/check").json()["skill"]
        assert checked["checks"]["complete"] and not checked["checks"]["executed"]
        registered = mutation(client, "post", base_url + "/register").json()["skill"]
        assert registered["registered"] and registered["validation_status"] == "unverified"
        assert client.get("/api/skills").json()["stats"]["registered"] == 1

        mutation(client, "post", base_url + "/meta", {"starred": True, "category": "办公", "tags": ["任务", "面板"]})
        relation_payload = {"from_type": "task", "from_id": "task-acceptance", "to_type": "skill", "to_id": skill_id}
        for _ in range(2):
            relations = mutation(client, "post", "/api/relations", relation_payload).json()["relations"]
        assert len(relations) == 1
        relation_id = relations[0]["id"]
        prompt = client.get(base_url + "/prompt", params={"task_id": "task-acceptance", "target": "验收 Mac 的 Codex"}).json()["prompt"]
        assert "制作每周任务看板" in prompt and edited["fingerprint"] in prompt
        assert "下载" in prompt and "附加" in prompt

        mutation(client, "post", base_url + "/validate", {"scenario": "第二周实际复用", "environment": "验收 Mac / Codex", "result": "success"}, expected=422)
        verified = mutation(client, "post", base_url + "/validate", {
            "scenario": "第二周实际复用", "environment": "验收 Mac / Codex", "result": "success",
            "evidence": "人工核对产物：任务齐全，HTML 可以独立打开",
        }).json()["skill"]
        assert verified["validation_status"] == "verified"
        assert verified["validations"][0]["current"] and verified["validations"][0]["manual"]

        # Change only the bundled template, through the draft edit API. The
        # manifest remains the same but the actual verified package changes.
        changed = mutation(client, "put", "/api/skills/drafts/" + skill_id, {
            "fingerprint": verified["fingerprint"],
            "resources": [{"filename": "templates/board.html", "text": "<main>second template</main>"}],
        }).json()["skill"]
        assert changed["manifest_fingerprint"] == verified["manifest_fingerprint"]
        assert changed["fingerprint"] != verified["fingerprint"]
        assert changed["validation_status"] == "outdated"
        assert changed["workflow"] == ["核对任务", "填入模板", "人工检查"]
        assert changed["validations"][0]["current"] is False
        assert client.get(base_url).json()["validation_status"] == "outdated"

        download = client.get(base_url + "/export")
        assert download.status_code == 200 and download.headers["content-type"] == "application/zip"
        assert changed["fingerprint"][:12] in download.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            assert {name.split("/", 1)[0] for name in archive.namelist()} == {"weekly-board"}
            assert archive.read("weekly-board/templates/board.html") == b"<main>second template</main>"
            assert "已整理好的每周任务面板方法" in archive.read("weekly-board/SKILL.md").decode("utf-8")
            report = json.loads(archive.read("weekly-board/WORKBENCH-EXPORT.json"))
            assert report["fingerprint"] == changed["fingerprint"] and report["complete"]
            assert report["directory_name_matches_manifest"]

        backup = client.get("/api/backup")
        assert backup.status_code == 200
        backup_bytes = backup.content
        with zipfile.ZipFile(io.BytesIO(backup_bytes)) as archive:
            assert "workbench.sqlite3" in archive.namelist() and "RESTORE.txt" in archive.namelist()
            drafts = [name for name in archive.namelist() if name.startswith("skills-drafts/") and name.endswith("templates/board.html")]
            previous = [name for name in archive.namelist() if name.startswith("skills-revisions/") and name.endswith("templates/board.html")]
            assert len(drafts) == 1 and archive.read(drafts[0]) == b"<main>second template</main>"
            assert any(archive.read(name) == b"<main>first template</main>" for name in previous)
        assert (source / "SKILL.md").read_bytes() == source_before

    # Follow the documented restore procedure to the same data path. Both
    # paths are inside pytest's private temporary directory, never real data.
    shutil.rmtree(data)
    with zipfile.ZipFile(io.BytesIO(backup_bytes)) as archive:
        archive.extractall(data)
    with TestClient(make_app(data, root), base_url=BASE_URL) as restored:
        bundle = restored.get("/api/bootstrap").json()
        recovered = next(item for item in bundle["skills"]["items"] if item["id"] == skill_id)
        assert recovered["registered"] and recovered["starred"]
        assert recovered["tags"] == ["任务", "面板"]
        assert recovered["fingerprint"] == changed["fingerprint"]
        assert recovered["validation_status"] == "outdated"
        assert any(relation["id"] == relation_id and relation["to_id"] == skill_id for relation in bundle["relations"])
        detail = restored.get("/api/skills/" + skill_id).json()
        assert detail["source_task_id"] == "task-acceptance"
        assert len(detail["validations"]) == 1 and detail["validations"][0]["fingerprint"] == verified["fingerprint"]
    assert (source / "SKILL.md").read_bytes() == source_before


def test_skill_api_reports_input_errors_without_mutating_sources(tmp_path):
    root, data = tmp_path / "sources", tmp_path / "data"
    source = existing_package(root)
    source_before = (source / "SKILL.md").read_bytes()
    with TestClient(make_app(data, root), base_url=BASE_URL) as client:
        existing = client.get("/api/skills").json()["items"][0]
        copied = client.get('/api/skills/' + existing['id'] + '/copy-target')
        assert copied.status_code == 200
        assert copied.json()['manifest_path'] == str(source.resolve() / 'SKILL.md')
        assert client.get('/api/skills/missing/copy-target').status_code == 404
        mutation(client, "put", "/api/skills/drafts/" + existing["id"], {"description": "禁止改写原包"}, expected=422)
        mutation(client, "post", "/api/skills/drafts", {
            "name": "invalid-resource", "description": "越界资源不可保存",
            "resources": [{"filename": "../outside.txt", "text": "must not write"}],
        }, expected=422)
        created = mutation(client, "post", "/api/skills/drafts", {
            "name": "incomplete-draft", "description": "尚缺资源",
            "body": "# 方法\n需要 `scripts/missing.py`。",
        }).json()["skill"]
        check = mutation(client, "post", "/api/skills/" + created["id"] + "/check").json()["skill"]
        assert check["checks"]["missing_references"] == ["scripts/missing.py"]
        mutation(client, "post", "/api/skills/" + created["id"] + "/register", expected=422)
        assert not client.get("/api/skills/" + created["id"]).json()["registered"]
        assert client.get("/api/skills/nonexistent").status_code == 404
        assert client.get("/api/skills/nonexistent/export").status_code == 404
        mutation(client, "post", "/api/skills/nonexistent/check", expected=404)
    assert (source / "SKILL.md").read_bytes() == source_before
    assert not (data / "outside.txt").exists()
