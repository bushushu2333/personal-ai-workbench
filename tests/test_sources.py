import copy
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from workbench.sources import SourcesService, safe_text


class MemoryStore:
    def __init__(self):
        self.data = {}
        self.lock = threading.RLock()

    def get(self, key, default=None):
        with self.lock:
            return copy.deepcopy(self.data.get(key, default))

    def set(self, key, value):
        with self.lock:
            self.data[key] = copy.deepcopy(value)


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tasks_root = self.root / "tasks-data"
        self.tasks_root.mkdir()
        self.store = MemoryStore()
        self.local = {"cpu_percent": 12.5, "memory_percent": 42.0, "disk_percent": 45.0,
                      "memory_used_gb": 10.0, "memory_total_gb": 24.0, "disk_free_gb": 100.0, "disk_total_gb": 200.0}
        with patch.object(SourcesService, "_refresh_agents", return_value={"status": "skipped"}), \
                patch.object(SourcesService, "_local_metrics", return_value=self.local):
            self.service = SourcesService(self.store, self.root / "data", task_root=self.tasks_root, start_background=False)

        for agent in self.store.get("sources.agents.records", []):
            self.service.agent_meta(agent["id"], {"enabled": True})

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def write_task(self, name="child", status="waiting-user", title="待确认任务", parent="main"):
        path = self.tasks_root / (name + ".md")
        path.write_text("---\nid: " + name + "\ntitle: " + title + "\npriority: 0\nstatus: " + status +
                        "\nparent: " + parent + "\nupdated: 2026-10-07\nsecrets: never-expose-this-value\nworkspace: /private/source\n---\n" +
                        "# 概要\n只读档案。\n## 当前卡点\n- 等待决定\n## 下一步\n1. 阅读需求\n" +
                        "## 事件日志\n- token=very-private-access-token\n## 策略与决策\nDo not expose arbitrary sections.\n", encoding="utf-8")
        return path

    def test_task_whitelist_original_state_parent_and_read_only(self):
        path = self.write_task(status="waiting-external")
        before = path.read_bytes()
        self.service.refresh("tasks")
        result = self.service.tasks()
        item = result["items"][0]
        self.assertEqual(item["status"], "waiting-external")
        self.assertEqual(item["parent"], "main")
        self.assertEqual(item["next"], ["阅读需求"])
        self.assertEqual(item["updated"], "2026-10-07")
        encoded = json.dumps(item, ensure_ascii=False)
        self.assertNotIn("never-expose", encoded)
        self.assertNotIn("/private/source", encoded)
        self.assertNotIn("very-private-access-token", encoded)
        self.assertNotIn("Do not expose arbitrary", encoded)
        self.assertEqual(path.read_bytes(), before)
        self.write_task(name="future", status="future-status")
        self.service.refresh("tasks")
        self.assertIn("future-status", [x["status"] for x in self.service.tasks()["items"]])

    def test_bad_file_isolated_and_previous_snapshot_preserved(self):
        path = self.write_task()
        other = self.write_task(name="good", title="旧标题")
        self.service.refresh("tasks")
        path.write_text("---\nid: [malformed\n---\n", encoding="utf-8")
        other.write_text(other.read_text().replace("旧标题", "新标题"), encoding="utf-8")
        self.service.refresh("tasks")
        result = self.service.tasks()
        by_id = {item["id"]: item for item in result["items"]}
        self.assertEqual(result["source_status"], "partial")
        self.assertEqual(by_id["child"]["source_status"], "stale")
        self.assertEqual(by_id["good"]["title"], "新标题")
        self.assertEqual(len(result["errors"]), 1)

    def test_unmounted_archive_retains_cached_tasks(self):
        self.write_task()
        self.service.refresh("tasks")
        self.tasks_root.rename(self.root / "detached")
        self.service.refresh("tasks")
        result = self.service.tasks()
        self.assertEqual(result["source_status"], "unavailable")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["source_status"], "unavailable")

    def test_directory_permission_denied_is_unavailable_not_false_empty(self):
        self.write_task()
        self.service.refresh("tasks")
        # Simulate pathlib.glob's permission-swallowing behaviour. The adapter
        # must not use that result to declare an empty, healthy archive.
        with patch("workbench.sources.Path.glob", return_value=[]) as glob, \
                patch("workbench.sources.Path.iterdir", side_effect=PermissionError("TCC denied")):
            self.service.refresh("tasks")
            glob.assert_not_called()
        result = self.service.tasks()
        self.assertEqual(result["source_status"], "unavailable")
        self.assertEqual(len(result["items"]), 1)
        self.assertIn("无读取权限", result["errors"][0])

    def test_task_symlink_cannot_escape_source(self):
        outside = self.root / "outside.md"
        outside.write_text("---\nid: outside\ntitle: private\n---\n", encoding="utf-8")
        (self.tasks_root / "outside.md").symlink_to(outside)
        self.service.refresh("tasks")
        result = self.service.tasks()
        self.assertEqual(result["items"], [])
        self.assertEqual(result["source_status"], "partial")

    def bridge_request(self, url, headers=None, timeout=None):
        if url.endswith("/healthz"):
            return 200, b"ok", {}
        if url.endswith("/status"):
            data = {"ts": int(time.time())}
            for platform in ("codex", "zcode", "kimi"):
                title = "token=top-secret-value".encode("gb2312").hex()
                data[platform] = {"ok": True, "running": 8, "waiting": 7,
                                  "items": [{"id": "%024x" % i, "t": title, "s": "W", "a": 15, "seen": False} for i in range(6)]}
            return 200, json.dumps(data).encode(), {}
        raise AssertionError("Unexpected endpoint: " + url)

    def test_bridge_counts_semantics_truncation_and_no_ack(self):
        with patch.object(self.service, "_request", side_effect=self.bridge_request) as request, \
                patch.object(self.service, "_process_states", return_value={"codex": "online", "zcode": "online", "kimi": "online"}), \
                patch.object(self.service, "_hermes_snapshot", return_value={"source_state": "unavailable"}):
            self.service.refresh("agents")
        codex = next(x for x in self.service.agents()["items"] if x["platform"] == "codex")
        self.assertEqual(codex["running"], 8)
        self.assertEqual(codex["completed_unread"], 7)
        self.assertEqual(len(codex["activities"]), 5)
        self.assertTrue(codex["activities_truncated"])
        self.assertFalse(codex["activity_list_complete"])
        self.assertEqual(codex["activities"][0]["reference_kind"], "activity_event")
        self.assertEqual(codex["activities"][0]["state"], "completed_unread")
        self.assertNotIn("top-secret-value", json.dumps(codex))
        self.assertIn("实时性待核实", codex["activity_label"])
        self.assertEqual({c.args[0].rsplit("/", 1)[-1] for c in request.call_args_list}, {"healthz", "status"})

    def test_bridge_failure_keeps_old_snapshot_but_never_fake_zero(self):
        with patch.object(self.service, "_request", side_effect=URLError("unavailable")), \
                patch.object(self.service, "_hermes_snapshot", return_value={"source_state": "unavailable"}):
            self.service.refresh("agents")
        codex = next(x for x in self.service.agents()["items"] if x["platform"] == "codex")
        self.assertIsNone(codex["running"])
        self.assertIsNone(codex["completed_unread"])
        with patch.object(self.service, "_request", side_effect=self.bridge_request), \
                patch.object(self.service, "_hermes_snapshot", return_value={"source_state": "unavailable"}):
            self.service.refresh("agents")
        with patch.object(self.service, "_request", side_effect=URLError("unavailable")), \
                patch.object(self.service, "_hermes_snapshot", return_value={"source_state": "unavailable"}):
            self.service.refresh("agents")
        codex = next(x for x in self.service.agents()["items"] if x["platform"] == "codex")
        self.assertEqual(codex["running"], 8)
        self.assertEqual(codex["source_state"], "unavailable")

    def test_hermes_stale_snapshot_does_not_claim_idle(self):
        home = self.root / "fake-home"
        (home / ".hermes").mkdir(parents=True)
        old = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        (home / ".hermes/gateway_state.json").write_text(json.dumps({"pid": 123, "active_agents": 0, "gateway_state": "running", "updated_at": old,
                                                                    "argv": ["secret-command-arg"]}))
        process = Mock()
        process.exe.return_value = "/Users/person/.hermes/venv/bin/python"
        with patch("workbench.sources.Path.home", return_value=home), patch("workbench.sources.psutil.Process", return_value=process):
            result = self.service._hermes_snapshot({}, datetime.now(timezone.utc).isoformat())
        self.assertEqual(result["process_state"], "online")
        self.assertEqual(result["source_state"], "stale")
        self.assertIsNone(result["running"])
        self.assertNotIn("secret-command-arg", json.dumps(result))

    def test_custom_device_never_runs_ssh_and_fixed_alias_cannot_redirect(self):
        with self.assertRaises(ValueError):
            self.service.device_save({"alias": "unconfigured-host"}, "local")
        with self.assertRaises(ValueError):
            self.service.device_save({"name": "custom", "source_kind": "ssh", "alias": "unconfigured-host"})
        saved = self.service.device_save({"name": "登记设备", "alias": "somewhere", "enabled": True})
        with patch.object(self.service, "_remote_metrics") as probe:
            self.service.refresh("devices", saved["id"])
            probe.assert_not_called()
        device = next(x for x in self.service.devices()["items"] if x["id"] == saved["id"])
        self.assertEqual(device["status"], "unconnected")
        self.assertIsNone(device["metrics"]["cpu_percent"])
        with patch("workbench.sources.subprocess.run") as run:
            with self.assertRaises(ValueError):
                self.service._remote_metrics("unconfigured-host")
            run.assert_not_called()

    def test_ssh_alias_is_verified_before_remote_probe(self):
        config = Mock(stdout="hostname 203.0.113.20\n", returncode=0)
        with patch("workbench.sources.REMOTE_HOSTS", {"example-ssh": "192.0.2.10"}), patch("workbench.sources.subprocess.run", return_value=config) as run:
            with self.assertRaises(ValueError):
                self.service._remote_metrics("example-ssh")
        self.assertEqual(run.call_count, 1)
        self.assertIn("-G", run.call_args.args[0])

    def test_stale_device_and_agent_getters_do_not_fetch_network(self):
        old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        self.store.set("sources.devices.snapshots", {"local": {"status": "ready", "last_success_at": old, "metrics": self.local}})
        self.store.set("sources.agents.snapshots", {"codex-local": {"source_state": "ready", "process_state": "online", "observed_at": old, "running": 2}})
        with patch.object(self.service, "_request") as request:
            device = next(x for x in self.service.devices()["items"] if x["id"] == "local")
            agent = next(x for x in self.service.agents()["items"] if x["id"] == "codex-local")
            request.assert_not_called()
        self.assertEqual(device["status"], "stale")
        self.assertEqual(agent["source_state"], "stale")
        self.assertEqual(agent["process_state"], "unknown")

    def test_news_etag_retry_after_attribution_and_metadata_preserved(self):
        response = {"items": [{"id": "one", "title": "资讯标题", "summary": "摘要", "source": {"name": "Original"},
                               "links": {"aihot": "https://aihot.news/item/one", "original": "https://example.org/one"},
                               "publishedAt": "2026-10-07T00:00:00Z", "category": "ai-products", "reason": "相关", "attribution": {"name": "AIHOT", "url": "https://aihot.news"}}]}
        with patch.object(self.service, "_request", return_value=(200, json.dumps(response).encode(), {"Cache-Control": "public, s-maxage=120", "ETag": 'W/"first"'})) as request:
            self.service.refresh("discover")
            self.service.refresh("discover")
            self.assertEqual(request.call_count, 1)
        item = self.service.discover()["items"][0]
        self.assertEqual(item["attribution"]["name"], "AIHOT")
        self.assertEqual(item["canonical_url"], "https://aihot.news/item/one")
        self.service.discover_meta(item["id"], {"bookmarked": True, "trial_status": "想试用"})
        state = self.store.get("sources.discover.http")
        state["next_allowed"] = 0
        self.store.set("sources.discover.http", state)
        with patch.object(self.service, "_request", return_value=(304, None, {"Cache-Control": "max-age=60"})) as request:
            self.service.refresh("discover")
            self.assertEqual(request.call_args.args[1]["If-None-Match"], 'W/"first"')
        self.assertTrue(self.service.discover()["items"][0]["bookmarked"])
        state = self.store.get("sources.discover.http")
        state["next_allowed"] = 0
        self.store.set("sources.discover.http", state)
        with patch.object(self.service, "_request", return_value=(429, None, {"Retry-After": "600"})) as request:
            self.service.refresh("discover")
            self.service.refresh("discover")
            self.assertEqual(request.call_count, 1)
        self.assertEqual(self.service.discover()["status"], "rate_limited")
        self.assertTrue(self.service.discover()["items"][0]["bookmarked"])
        self.assertGreater(self.store.get("sources.discover.http")["next_allowed"] - time.time(), 590)

    def test_github_add_is_canonical_and_deduplicated(self):
        metadata = {"full_name": "owner/repo", "description": "Useful tool", "license": {"spdx_id": "MIT"}, "topics": ["ai"]}
        with patch.object(self.service, "_request", return_value=(200, json.dumps(metadata).encode(), {})) as request:
            first = self.service.add_project({"url": "https://github.com/owner/repo.git"})
            second = self.service.add_project({"url": "https://github.com/owner/repo/"})
            self.assertEqual(request.call_count, 1)
        self.assertEqual(first["id"], second["id"])
        item = self.service.discover()["items"][0]
        self.assertEqual(item["url"], "https://github.com/owner/repo")
        self.assertEqual(item["license"], "MIT")
        with self.assertRaises(ValueError):
            self.service.add_project({"url": "http://127.0.0.1/private"})

    def github_page(self, license_name="Apache-2.0", owner="owner", repo="repo"):
        return {"meta": {"title": "GitHub - %s/%s: Browser automation tool" % (owner, repo)},
                "payload": {"codeViewRepoRoute": {"about": {"topics": ["testing", {"name": "automation"}]},
                    "overview": {"overviewFiles": [{"displayName": "README.md", "richText": "<script>never execute or expose</script>"},
                        {"displayName": "LICENSE", "tabName": license_name}]}}}}

    def test_github_api_403_falls_back_to_same_repository_public_json(self):
        denied = HTTPError("https://api.github.com/repos/owner/repo", 403, "rate limit", {"X-RateLimit-Remaining": "0"}, None)
        body = json.dumps(self.github_page()).encode()
        with patch.object(self.service, "_request", side_effect=[denied, (200, body, {})]) as request:
            result = self.service.add_project({"url": "https://github.com/owner/repo"})
        self.assertEqual(result["metadata_status"], "ready")
        self.assertEqual(result["metadata_source"], "github-public-page")
        self.assertEqual(request.call_args_list[1].args[0], "https://github.com/owner/repo")
        item = self.service.discover()["items"][0]
        self.assertEqual(item["summary"], "Browser automation tool")
        self.assertEqual(item["tags"], ["testing", "automation"])
        self.assertEqual(item["license"], "Apache-2.0")
        self.assertNotIn("script", json.dumps(item))

    def test_github_failed_duplicate_can_refresh_without_duplicate_record(self):
        denied = HTTPError("https://api.github.com/repos/owner/repo", 403, "rate limit", {}, None)
        with patch.object(self.service, "_request", side_effect=[denied, URLError("page unavailable")]):
            first = self.service.add_project({"url": "https://github.com/owner/repo"})
        self.assertEqual(first["metadata_status"], "unavailable")
        with patch.object(self.service, "_request", return_value=(200, json.dumps(self.github_page()).encode(), {})) as request:
            retried = self.service.add_project({"url": "https://github.com/owner/repo"})
            successful_duplicate = self.service.add_project({"url": "https://github.com/owner/repo"})
        self.assertEqual(request.call_count, 1)  # Rate-limited API stays in cooldown.
        self.assertEqual(request.call_args.args[0], "https://github.com/owner/repo")
        self.assertEqual(first["id"], retried["id"])
        self.assertEqual(retried["metadata_status"], "ready")
        self.assertTrue(successful_duplicate["existing"])
        self.assertEqual(len(self.store.get("sources.discover.projects")), 1)

    def test_github_page_does_not_guess_license_or_accept_different_repository(self):
        fields = self.service._github_page_fields(self.github_page("License"), "owner", "repo")
        self.assertIsNone(fields["license"])
        with self.assertRaises(ValueError):
            self.service._github_page_fields(self.github_page(owner="someone-else"), "owner", "repo")

    def test_saved_news_survives_feed_eviction_and_service_reload(self):
        item = {"id": "aihot:saved", "kind": "news", "title": "值得保留的消息", "summary": "摘要", "tags": [],
                "url": "https://example.org/saved", "bookmarked": False, "trial_status": None}
        self.store.set("sources.discover.cache", {"items": [item], "status": "ready", "updated_at": "2026-10-07"})
        self.service.discover_meta(item["id"], {"bookmarked": True})
        with patch.object(self.service, "_request", return_value=(200, b'{"items": []}', {})):
            self.service.refresh("discover")
        self.assertEqual(self.store.get("sources.discover.cache")["items"], [])
        self.assertIn(item["id"], self.store.get("sources.discover.saved"))
        with patch.object(SourcesService, "_refresh_agents", return_value={"status": "skipped"}), \
                patch.object(SourcesService, "_local_metrics", return_value=self.local):
            reloaded = SourcesService(self.store, self.root / "data", task_root=self.tasks_root, start_background=False)
        try:
            visible = reloaded.discover()["items"]
            self.assertEqual(len(visible), 1)
            self.assertTrue(visible[0]["bookmarked"])
            self.assertTrue(visible[0]["outside_current_window"])
        finally:
            reloaded.close()

    def test_trial_retains_saved_snapshot_until_all_personal_flags_removed(self):
        item = {"id": "aihot:trial", "kind": "project", "title": "试用工具", "summary": "", "tags": [],
                "url": "https://github.com/example/tool", "bookmarked": False, "trial_status": None}
        self.store.set("sources.discover.cache", {"items": [item], "status": "ready"})
        self.service.discover_meta(item["id"], {"bookmarked": True, "trial_status": "试用中"})
        self.store.set("sources.discover.cache", {"items": [], "status": "ready"})
        self.service.discover_meta(item["id"], {"bookmarked": False})
        self.assertEqual(self.service.discover()["items"][0]["trial_status"], "试用中")
        self.service.discover_meta(item["id"], {"trial_status": None})
        self.assertEqual(self.service.discover()["items"], [])
        self.assertEqual(self.store.get("sources.discover.saved"), {})

    def test_relation_only_discovery_survives_eviction_without_forced_bookmark(self):
        item = {"id": "aihot:linked", "kind": "news", "title": "关联资讯", "summary": "", "tags": [],
                "url": "https://example.org/linked", "bookmarked": False, "trial_status": None,
                "unexpected_private_data": "must-not-be-persisted"}
        self.store.set("sources.discover.cache", {"items": [item], "status": "ready"})
        self.service.preserve_discovery(item["id"])
        self.store.set("relations", [{"id": "relation1", "from_type": "discover", "from_id": item["id"], "to_type": "task", "to_id": "t1"}])
        self.store.set("sources.discover.cache", {"items": [], "status": "ready"})
        self.service.discover_meta(item["id"], {"bookmarked": False, "trial_status": None})
        visible = self.service.discover()["items"]
        self.assertEqual(len(visible), 1)
        self.assertFalse(visible[0]["bookmarked"])
        self.assertNotIn("unexpected_private_data", self.store.get("sources.discover.saved")[item["id"]])
        # Once unlinked, removing the personal flags can remove the snapshot.
        self.store.set("relations", [])
        self.service.discover_meta(item["id"], {"bookmarked": False, "trial_status": None})
        self.assertEqual(self.service.discover()["items"], [])

    def test_to_discovery_reference_and_upstream_id_change_preserve_endpoint(self):
        item = {"id": "aihot:old-linked", "kind": "news", "title": "关联资讯", "summary": "", "tags": [],
                "url": "https://example.org/stable-link", "bookmarked": False, "trial_status": None}
        self.store.set("sources.discover.cache", {"items": [item], "status": "ready"})
        self.service.preserve_discovery(item["id"])
        self.store.set("relations", [{"from_type": "task", "from_id": "t1", "to_type": "discover", "to_id": item["id"]}])
        self.store.set("sources.discover.cache", {"items": [dict(item, id="aihot:new-id", title="新资讯标题")], "status": "ready"})
        self.service.discover_meta(item["id"], {"bookmarked": False})
        visible = self.service.discover()["items"]
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]["id"], item["id"])
        self.assertEqual(visible[0]["title"], "新资讯标题")
        with self.assertRaises(KeyError):
            self.service.preserve_discovery("missing-news")

    def test_saved_personal_identity_survives_upstream_id_change_at_same_url(self):
        original = {"id": "aihot:old-id", "kind": "news", "title": "旧标题", "summary": "", "tags": [],
                    "url": "https://example.org/unchanged", "bookmarked": False, "trial_status": None}
        self.store.set("sources.discover.cache", {"items": [original], "status": "ready"})
        self.service.discover_meta(original["id"], {"bookmarked": True})
        self.store.set("sources.discover.cache", {"items": [dict(original, id="aihot:new-id", title="新标题")], "status": "ready"})
        items = self.service.discover()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "aihot:old-id")
        self.assertEqual(items[0]["title"], "新标题")
        self.assertTrue(items[0]["bookmarked"])
        self.service.discover_meta(items[0]["id"], {"bookmarked": False})
        self.assertFalse(self.service.discover()["items"][0]["bookmarked"])

    def test_interest_matching_is_real_dynamic_and_preserves_source_reason(self):
        items = [
            {"id": "a", "title": "AI Agent 工具", "summary": "课堂里的探索", "tags": ["开源"], "url": "https://example.org/a", "reason": "来源推荐理由"},
            {"id": "b", "title": "He said hello", "summary": "普通消息", "tags": [], "url": "https://example.org/b", "reason": "另一个理由"},
        ]
        self.store.set("sources.discover.cache", {"items": items, "status": "ready"})
        self.store.set("settings", {"interests": ["ai", "课堂", "开源"]})
        with patch.object(self.service, "_request") as request:
            visible = self.service.discover()["items"]
            request.assert_not_called()
        self.assertTrue(visible[0]["is_relevant"])
        self.assertEqual(visible[0]["interest_matches"], ["ai", "课堂", "开源"])
        self.assertEqual(visible[0]["reason"], "来源推荐理由")
        self.assertFalse(visible[1]["is_relevant"])
        self.store.set("settings", {"interests": ["普通"]})
        visible = self.service.discover()["items"]
        self.assertFalse(visible[0]["is_relevant"])
        self.assertTrue(visible[1]["is_relevant"])
        self.store.set("settings", {"interests": []})
        self.assertFalse(any(item["is_relevant"] for item in self.service.discover()["items"]))


if __name__ == "__main__":
    unittest.main()
