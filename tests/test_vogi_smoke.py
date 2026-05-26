from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.db import Storage
from backend.exceptions import ModelProviderError
from backend.services.agent import AgentService
from backend.services.bootstrap import BootstrapService
from backend.services.browser_sessions import BrowserSessionManager
from backend.services.capabilities import HierarchicalPlanner
from backend.services.model_router import ModelRouter
from backend.services.tools import ToolService
from backend.services.web_retrieval import WebRetrievalService
import backend.app as app_module


class FakeEndpointAgent:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, task, history, project_root, emit=None, project_id=None, planning_mode=False, attachments=None, permission_mode="safe"):
        self.calls.append({
            "task": task,
            "history": history,
            "project_root": project_root,
            "project_id": project_id,
            "planning_mode": planning_mode,
            "attachments": attachments or [],
            "permission_mode": permission_mode,
        })
        if emit:
            value = emit({"type": "trace", "entry": {"type": "tool", "action": {"tool": "list_dir"}}, "transcript": []})
            if asyncio.iscoroutine(value):
                await value
        return {"final": "ok", "summary": ["ok"], "files": [], "plan": ["done"], "transcript": []}


class FakeLoopModel:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, **_kwargs):
        self.calls += 1
        if self.calls <= 4:
            return {"message": {"content": json.dumps({
                "action": {"tool": "read_file", "args": {"path": "Frontend/index.html", "max_chars": 1000}},
                "plan": ["inspect ui"],
                "status": "reading",
            })}}
        return {"message": {"content": json.dumps({"final": "Recovered.", "summary": ["guard worked"], "files": []})}}


class FakeRepeatedEmptySearchModel:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, **_kwargs):
        self.calls += 1
        if self.calls <= 3:
            return {"message": {"content": json.dumps({
                "action": {"tool": "search_text", "args": {"path": ".", "query": "definitely-not-present-vogi-token"}},
                "plan": ["search targeted text"],
                "status": "searching",
            })}}
        return {"message": {"content": json.dumps({"final": "Recovered from empty search.", "summary": ["guard worked"], "files": []})}}


class FakeEmptyUpgradeModel:
    async def chat(self, messages, **_kwargs):
        return {"message": {"content": ""}}


class FakeFailingUpgradeModel:
    async def chat(self, messages, **_kwargs):
        raise ModelProviderError("HTTP 429: Too Many Requests")


class FakeCodeChatModel:
    async def chat(self, messages, **_kwargs):
        return {"message": {"content": "const answer = 42;\nconsole.log(answer);"}}


class FakeContextCaptureModel:
    def __init__(self) -> None:
        self.messages = []
        self.message_calls = []

    async def chat(self, messages, **_kwargs):
        self.messages = copy.deepcopy(messages)
        self.message_calls.append(copy.deepcopy(messages))
        return {"message": {"content": json.dumps({"final": "Context captured.", "summary": ["ok"], "files": []})}}


class FakeUpgradeMustEditModel:
    def __init__(self) -> None:
        self.calls = 0
        self.message_calls = []

    async def chat(self, messages, **_kwargs):
        self.message_calls.append(copy.deepcopy(messages))
        self.calls += 1
        if self.calls == 1:
            return {"message": {"content": json.dumps({
                "final": "Paste this CSS into your app.",
                "summary": ["gave snippet"],
                "files": [],
            })}}
        if self.calls == 2:
            return {"message": {"content": json.dumps({
                "action": {"tool": "write_file", "args": {"path": "Frontend/raw-platform.js", "content": "console.log('edited');"}},
                "plan": ["edit Vogi file"],
                "status": "editing real file",
            })}}
        return {"message": {"content": json.dumps({
            "final": "Edited Vogi.",
            "summary": ["edited"],
            "files": ["Frontend/raw-platform.js"],
        })}}


class FakeOutOfScopeUpgradeModel:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return {"message": {"content": json.dumps({
                "action": {"tool": "recall_project", "args": {"project_id": "should-not-run"}},
                "plan": ["retrieve memory"],
                "status": "reading memory",
            })}}
        if self.calls == 2:
            return {"message": {"content": json.dumps({
                "action": {"tool": "write_file", "args": {"path": "backend/change.py", "content": "updated = True\n"}},
                "plan": ["edit source"],
                "status": "editing source",
            })}}
        return {"message": {"content": json.dumps({"final": "Edited source.", "summary": ["edited"], "files": ["backend/change.py"]})}}


class FakeNoWriteToolService:
    def __init__(self, settings, storage) -> None:
        self.settings = settings
        self.storage = storage
        self.actions = []

    def normalize_path(self, target=None, root=None):
        base = Path(root or self.settings.root_dir)
        raw = Path(target or ".")
        return raw if raw.is_absolute() else (base / raw).resolve()

    async def execute(self, action, root, permission_mode="safe"):
        self.actions.append(action)
        tool = action.get("tool")
        args = action.get("args") or {}
        if tool == "write_file":
            return {
                "written": str((Path(root) / args.get("path", "unknown")).resolve()),
                "path": str((Path(root) / args.get("path", "unknown")).resolve()),
                "bytes": len(str(args.get("content", "")).encode("utf-8")),
                "additions": 1,
                "deletions": 0,
                "changed": True,
            }
        if tool == "read_file":
            return "fake file"
        if tool == "run_shell":
            return {"exitCode": 0, "stdout": "ok", "stderr": ""}
        return []


class FakeConsumerModel:
    def __init__(self, decisions) -> None:
        self.decisions = list(decisions)
        self.calls = 0

    async def chat(self, messages, **_kwargs):
        self.calls += 1
        if self.decisions:
            decision = self.decisions.pop(0)
        else:
            decision = {"final": "Done.", "summary": ["ok"], "files": []}
        return {"message": {"content": json.dumps(decision)}}


class FakeConsumerToolService:
    def __init__(self, settings, storage) -> None:
        self.settings = settings
        self.storage = storage
        self.actions = []

    def normalize_path(self, target=None, root=None):
        base = Path(root or self.settings.root_dir)
        raw = Path(target or ".")
        return raw if raw.is_absolute() else (base / raw).resolve()

    async def execute(self, action, root, permission_mode="safe"):
        self.actions.append(action)
        tool = action.get("tool")
        args = action.get("args") or {}
        if tool == "browse_jobs":
            return {"results": [{"title": "React Developer", "company": "Acme", "location": "remote", "url": "https://jobs.example/react", "snippet": "React remote role"}]}
        if tool == "web_search":
            return {"results": [{"title": "iPhone price", "url": "https://shop.example/iphone", "snippet": "iPhone price ₹79900"}]}
        if tool == "browse_url":
            return {"url": args.get("url"), "statusCode": 200, "text": "Example Domain"}
        if tool == "search_text":
            return [{"path": str(Path(root) / "frontend.js"), "lineNumber": 1, "line": "skills sidebar"}]
        if tool == "recall_project":
            return [{"key": "stack", "value": {"backend": "FastAPI", "frontend": "vanilla JS"}}]
        if tool == "create_artifact":
            target = self.normalize_path(args.get("path") or "report.md", root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(args.get("content") or "artifact"), encoding="utf-8")
            return {"created": str(target), "format": args.get("format") or "md", "bytes": target.stat().st_size}
        return {"ok": True}


class FakeRenderedBrowser:
    def __init__(self, payload=None) -> None:
        self.payload = payload or {}
        self.urls = []

    async def render_public(self, url):
        self.urls.append(url)
        return self.payload

    async def read_authenticated(self, url):
        self.urls.append(url)
        return self.payload


class FakeHttpClient:
    def __init__(self, response) -> None:
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, *_args, **_kwargs):
        return self.response


class VogiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = tempfile.TemporaryDirectory()
        self.settings = get_settings().model_copy(deep=True)
        self.settings.root_dir = Path(self.temp_root.name).resolve()
        self.settings.database_url = "json://isolated-tests"
        self.original_app_dependencies = (
            app_module.settings,
            app_module.storage,
            app_module.tools,
            app_module.bootstrap_service,
        )
        app_module.settings = self.settings
        app_module.storage = Storage(self.settings)
        app_module.tools = ToolService(self.settings, app_module.storage)
        app_module.bootstrap_service = BootstrapService(self.settings, app_module.storage)
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        (
            app_module.settings,
            app_module.storage,
            app_module.tools,
            app_module.bootstrap_service,
        ) = self.original_app_dependencies
        self.temp_root.cleanup()

    def test_upload_returns_text_and_binary_preview(self) -> None:
        text_response = self.client.post("/api/files/upload", files={"file": ("note.txt", b"hello vogi", "text/plain")})
        self.assertEqual(text_response.status_code, 200)
        self.assertEqual(text_response.json()["upload"]["preview"], "hello vogi")

        binary_response = self.client.post("/api/files/upload", files={"file": ("blob.bin", b"\xff\x00\x01", "application/octet-stream")})
        self.assertEqual(binary_response.status_code, 200)
        self.assertTrue(binary_response.json()["upload"]["preview"])

    def test_agent_endpoint_passes_prompt_scoped_attachments_and_plan_flag_without_disabling_tools(self) -> None:
        fake = FakeEndpointAgent()
        with patch.object(app_module, "agent_service", fake):
            response = self.client.post("/api/agent", json={
                "task": "/upgrade improve the sidebar",
                "history": [{"role": "assistant", "content": "ready", "attachments": [{"id": "old"}]}],
                "attachments": [{"id": "new", "filename": "brief.txt", "contentType": "text/plain", "size": 5, "preview": "brief"}],
                "planningMode": False,
                "permissionMode": "full",
            })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(fake.calls[0]["planning_mode"])
        self.assertEqual(fake.calls[0]["attachments"][0]["id"], "new")
        self.assertEqual(fake.calls[0]["permission_mode"], "full")

    def test_agent_stream_accepts_prompt_scoped_attachments(self) -> None:
        fake = FakeEndpointAgent()
        with patch.object(app_module, "agent_service", fake):
            with self.client.stream("POST", "/api/agent/stream", json={
                "task": "/docs create a one page report",
                "attachments": [{"id": "stream-file", "filename": "report-notes.txt", "contentType": "text/plain", "size": 12, "preview": "notes"}],
                "planningMode": False,
            }) as response:
                body = "".join(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk for chunk in response.iter_bytes())
        self.assertEqual(response.status_code, 200)
        self.assertIn('"type": "done"', body)
        self.assertEqual(fake.calls[0]["attachments"][0]["id"], "stream-file")

    def test_tool_endpoint_passes_full_permission_to_powershell_execution(self) -> None:
        response = self.client.post("/api/tools/run", json={
            "permissionMode": "full",
            "action": {"tool": "run_shell", "args": {"command": "Write-Output 'endpoint-powershell-ok'"}},
        })

        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertEqual(result["permissionMode"], "full")
        self.assertIn("endpoint-powershell-ok", result["stdout"])

    def test_project_id_root_wins_over_frontend_project_root(self) -> None:
        fake = FakeEndpointAgent()
        with tempfile.TemporaryDirectory() as tmp:
            created = self.client.post("/api/projects", json={"name": "Scoped", "rootPath": tmp}).json()
            with patch.object(app_module, "agent_service", fake):
                response = self.client.post("/api/agent", json={
                    "task": "/code list files",
                    "projectId": created["project"]["id"],
                    "projectRoot": "C:/should/not/win",
                })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Path(fake.calls[0]["project_root"]).resolve(), Path(tmp).resolve())
        self.assertEqual(created["project"]["kind"], "external")

    def test_new_project_creates_unique_managed_directory(self) -> None:
        first = self.client.post("/api/projects", json={"name": "Project"}).json()["project"]
        second = self.client.post("/api/projects", json={"name": "Project"}).json()["project"]

        self.assertEqual(first["kind"], "managed")
        self.assertEqual(second["kind"], "managed")
        self.assertNotEqual(first["rootPath"], second["rootPath"])
        self.assertEqual(Path(first["rootPath"]).parent, self.settings.projects_dir)
        self.assertTrue(Path(first["rootPath"]).is_dir())
        self.assertTrue(Path(second["rootPath"]).is_dir())

    def test_delete_managed_project_keeps_project_files(self) -> None:
        project = self.client.post("/api/projects", json={"name": "Keep Files"}).json()["project"]
        marker = Path(project["rootPath"]) / "keep.txt"
        marker.write_text("retain me", encoding="utf-8")

        response = self.client.delete(f"/api/projects/{project['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(marker.exists())
        self.assertIsNone(app_module.storage.get_project(project["id"]))

    def test_planner_skill_smoke_matrix(self) -> None:
        planner = HierarchicalPlanner()
        cases = {
            "/upgrade adjust the frontend": "write_file",
            "/code inspect this repo": "run_shell",
            "/docs create a pdf": "create_artifact",
            "/jobs prepare frontend applications": "prepare_job_application",
            "/memory remember this stack": "remember_project",
            "/tool create a command": "create_command_tool",
            "/web search latest AI news": "web_search",
            "install redis on this computer": "install_package",
        }
        for prompt, expected_tool in cases.items():
            with self.subTest(prompt=prompt):
                plan = planner.plan(prompt)
                self.assertIn(expected_tool, plan["allowedTools"])

    def test_redis_install_routes_to_real_install_action(self) -> None:
        runtime_plan = HierarchicalPlanner().plan("install redis on this Windows machine")
        action = AgentService.required_first_action("install redis on this Windows machine", runtime_plan)

        self.assertEqual(runtime_plan["intent"], "system.install")
        self.assertEqual(action["action"]["tool"], "install_package")
        self.assertEqual(action["action"]["args"]["package"], "Redis.Redis")

    def test_shell_runs_actual_powershell_expressions_and_returns_stdout(self) -> None:
        tools = ToolService(self.settings, Storage(self.settings))

        result = asyncio.run(tools.run_shell(
            "Write-Output 'hello'; ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)",
            ".",
            20000,
            self.settings.root_dir,
        ))

        self.assertEqual(result["shell"], "powershell")
        self.assertEqual(result["exitCode"], 0)
        self.assertIn("hello", result["stdout"])
        self.assertIn("False", result["stdout"])

    def test_safe_mode_blocks_install_and_full_mode_can_invoke_installer(self) -> None:
        tools = ToolService(self.settings, Storage(self.settings))
        with self.assertRaisesRegex(Exception, "Full Access"):
            asyncio.run(tools.install_package({"manager": "winget", "package": "Redis.Redis"}, self.settings.root_dir, "safe"))

        with patch.object(tools, "run_shell", new=AsyncMock(return_value={"exitCode": 0, "stdout": "installed", "stderr": ""})) as runner:
            result = asyncio.run(tools.install_package({"manager": "winget", "package": "Redis.Redis"}, self.settings.root_dir, "full"))

        self.assertTrue(result["installed"])
        self.assertIn("winget install", runner.await_args.args[0])

    def test_database_query_supports_reads_and_enforces_mutation_mode(self) -> None:
        tools = ToolService(self.settings, Storage(self.settings))
        db_path = self.settings.root_dir / "queries.db"
        connection_url = f"sqlite:///{db_path.as_posix()}"

        tools.database_query({"connectionUrl": connection_url, "sql": "CREATE TABLE items (name TEXT)"}, "full")
        tools.database_query({"connectionUrl": connection_url, "sql": "INSERT INTO items(name) VALUES ('ready')"}, "full")
        result = tools.database_query({"connectionUrl": connection_url, "sql": "SELECT name FROM items"}, "safe")

        self.assertEqual(result["rows"], [{"name": "ready"}])
        with self.assertRaisesRegex(Exception, "Safe Mode"):
            tools.database_query({"connectionUrl": connection_url, "sql": "DELETE FROM items"}, "safe")

    def test_upgrade_mentions_memory_but_stays_in_coding_mode(self) -> None:
        plan = HierarchicalPlanner().plan("/upgrade automatically save chats and memory")

        self.assertEqual(plan["intent"], "coding.execute")
        self.assertIn("write_file", plan["allowedTools"])
        self.assertNotIn("recall_project", plan["allowedTools"])
        self.assertNotIn("remember_project", plan["allowedTools"])

    def test_consumer_agent_task_routing_matrix(self) -> None:
        planner = HierarchicalPlanner()
        cases = [
            ("Check and compare iPhone 17 prices in India, find the cheapest option, and create a lowest-price graph", {"web_search", "browse_url", "create_artifact"}),
            ("Browse frontend developer jobs in Bengaluru and prepare applications", {"browse_jobs", "prepare_job_application"}),
            ("Create a PDF invoice template for my freelance client", {"create_artifact"}),
            ("Turn these notes into presentation slides", {"create_slides"}),
            ("Fix the login button bug in this project", {"find_files", "read_file", "write_file", "run_shell"}),
            ("Search the web for current GST filing deadline", {"web_search", "browse_url"}),
            ("Remember that this project uses FastAPI and Tailwind", {"remember_project"}),
            ("Recall what stack this project uses", {"recall_project"}),
            ("Create a reusable test command tool", {"create_command_tool"}),
            ("List files and find where the sidebar is defined", {"find_files", "search_text"}),
            ("Read the README and summarize setup", {"read_file"}),
            ("Generate a one page project report as docx", {"create_artifact"}),
            ("Find remote React jobs and build a cover letter packet", {"browse_jobs", "prepare_job_application"}),
            ("Check a website URL and summarize it", {"browse_url"}),
            ("Run tests locally and tell me failures", {"run_shell"}),
        ]
        for prompt, expected_tools in cases:
            with self.subTest(prompt=prompt):
                plan = planner.plan(prompt)
                self.assertTrue(expected_tools.issubset(set(plan["allowedTools"])), plan)

    def test_25_real_consumer_prompts_route_to_required_tools(self) -> None:
        planner = HierarchicalPlanner()
        cases = [
            ("Compare current iPhone 17 prices in India and create a lowest-price graph", {"web_search", "browse_url", "create_artifact"}),
            ("Compare Samsung Galaxy S25 Ultra vs iPhone 17 buying options in India", {"web_search", "browse_url"}),
            ("Find current remote React developer jobs and prepare an application summary", {"browse_jobs", "prepare_job_application"}),
            ("Find frontend developer jobs in Bengaluru and prepare an application email", {"browse_jobs", "prepare_job_application"}),
            ("Search current GST filing deadline with source URLs", {"web_search", "browse_url"}),
            ("Summarize latest AI news today with URLs", {"web_search", "browse_url"}),
            ("Open https://example.com and summarize it", {"browse_url"}),
            ("Inspect a local project and find where sidebar skills text appears", {"search_text", "read_file"}),
            ("Read README and summarize setup", {"read_file"}),
            ("Fix a tiny failing local test and rerun tests", {"read_file", "write_file", "run_shell"}),
            ("Create a PDF invoice template", {"create_artifact"}),
            ("Create slides from notes", {"create_slides"}),
            ("Remember project stack", {"remember_project"}),
            ("Recall project stack without unnecessary tests", {"recall_project"}),
            ("Create a safe reusable command tool in the project scope", {"create_command_tool"}),
            ("Search for a product deal and identify cheapest trusted seller", {"web_search", "browse_url"}),
            ("Research a travel visa current-info query with URLs", {"web_search", "browse_url"}),
            ("Summarize a public documentation page", {"browse_url"}),
            ("Create a one-page report from web research", {"web_search", "create_artifact"}),
            ("Run local tests and report failures only", {"run_shell"}),
            ("Check current laptop deals and compare prices", {"web_search", "browse_url"}),
            ("Find internships and write a short outreach email", {"browse_jobs"}),
            ("Make a chart from latest market prices", {"web_search", "create_artifact"}),
            ("Where is the settings button defined in this project", {"search_text"}),
            ("Look up current exchange rate and cite source", {"web_search", "browse_url"}),
        ]
        for prompt, expected_tools in cases:
            with self.subTest(prompt=prompt):
                plan = planner.plan(prompt)
                self.assertTrue(expected_tools.issubset(set(plan["allowedTools"])), plan)

    def test_repeated_read_guard_recovers(self) -> None:
        settings = self.settings
        storage = Storage(settings)
        tools = ToolService(settings, storage)
        agent = AgentService(settings, FakeLoopModel(), tools)

        async def run():
            return await agent.run("/code remove local text", [], str(settings.root_dir), planning_mode=False)

        result = asyncio.run(run())
        self.assertEqual(result["final"], "Recovered.")
        self.assertTrue(any(
            isinstance(entry.get("observation"), dict)
            and str(entry["observation"].get("error", "")).startswith("Repeated read_file blocked")
            for entry in result["transcript"]
        ))

    def test_write_file_reports_line_delta_for_change_summary(self) -> None:
        settings = self.settings
        storage = Storage(settings)
        tools = ToolService(settings, storage)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "demo.txt"
            target.write_text("old\nsame\nremove\n", encoding="utf-8")
            result = tools.write_or_append("write_file", {"path": "demo.txt", "content": "new\nsame\nadd\n"}, root)
        self.assertEqual(result["additions"], 2)
        self.assertEqual(result["deletions"], 2)
        self.assertTrue(result["changed"])

    def test_empty_search_repeat_is_blocked_and_recovers(self) -> None:
        settings = self.settings
        storage = Storage(settings)
        tools = ToolService(settings, storage)
        agent = AgentService(settings, FakeRepeatedEmptySearchModel(), tools)

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "empty.txt").write_text("nothing useful here", encoding="utf-8")

            async def run():
                return await agent.run("/code find the missing token", [], tmp, planning_mode=False)

            result = asyncio.run(run())
        self.assertEqual(result["final"], "Recovered from empty search.")
        self.assertTrue(any(
            isinstance(entry.get("observation"), dict)
            and "no useful results" in str(entry["observation"].get("error", ""))
            for entry in result["transcript"]
        ))

    def test_code_search_ignores_runtime_state_and_backups(self) -> None:
        storage = Storage(self.settings)
        tools = ToolService(self.settings, storage)
        source = self.settings.root_dir / "backend" / "source.py"
        state_backup = self.settings.root_dir / ".vogi-state" / "state.backup.json"
        source.parent.mkdir(parents=True, exist_ok=True)
        state_backup.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("save_memory_marker = True\n", encoding="utf-8")
        state_backup.write_text("save_memory_marker", encoding="utf-8")

        results = tools.search_text({"path": ".", "query": "save_memory_marker"}, self.settings.root_dir)

        self.assertEqual([Path(item["path"]).name for item in results], ["source.py"])

    def test_search_parser_normalizes_general_web_results(self) -> None:
        html = """
        <div class="result">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.gov%2Fdeadline">Official Deadline</a>
          <a class="result__snippet">Current filing information from the official portal.</a>
        </div>
        """

        results = WebRetrievalService.parse_search_results(html, 5)

        self.assertEqual(results[0]["url"], "https://example.gov/deadline")
        self.assertEqual(results[0]["snippet"], "Current filing information from the official portal.")
        self.assertEqual(results[0]["sourceDomain"], "example.gov")

    def test_search_falls_back_to_rendered_results_when_http_is_blocked(self) -> None:
        rendered_html = """
        <div class="result">
          <a class="result__a" href="https://docs.example/reference">Reference</a>
          <a class="result__snippet">Rendered search result.</a>
        </div>
        """
        browser = FakeRenderedBrowser({"html": rendered_html, "text": "Reference", "url": "https://html.duckduckgo.com/html/"})
        retrieval = WebRetrievalService(self.settings, browser)
        blocked = httpx.Response(
            200,
            text="<html>Verify you are human captcha</html>",
            request=httpx.Request("GET", "https://html.duckduckgo.com/html/"),
        )

        with patch("backend.services.web_retrieval.httpx.AsyncClient", return_value=FakeHttpClient(blocked)):
            result = asyncio.run(retrieval.search({"query": "reference material"}))

        self.assertEqual(result["retrievalMode"], "rendered")
        self.assertEqual(result["results"][0]["url"], "https://docs.example/reference")

    def test_html_extraction_reads_structured_facts_before_model_text_truncation(self) -> None:
        retrieval = WebRetrievalService(self.settings, FakeRenderedBrowser())
        long_prefix = "<main>" + ("intro " * 3000) + "</main>"
        structured = """<script type="application/ld+json">[
        {"@type":"Article","headline":"Verified update","datePublished":"2026-05-26"},
        {"@type":"Product","name":"Public item","offers":[{"@type":"Offer","price":"1250","priceCurrency":"INR"}]}
        ]</script>"""
        response = httpx.Response(
            200,
            text=f"<html><title>Source</title>{long_prefix}{structured}</html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "https://example.com/update"),
        )

        result = retrieval.extract_response(response, 1000)

        self.assertLessEqual(len(result["text"]), 1050)
        self.assertEqual(result["facts"][0]["headline"], "Verified update")
        self.assertEqual(result["facts"][0]["datePublished"], "2026-05-26")
        self.assertEqual(result["facts"][1]["offers"][0]["price"], "1250")

    def test_auto_browse_uses_rendered_page_when_raw_html_has_no_content(self) -> None:
        browser = FakeRenderedBrowser({
            "url": "https://app.example/dashboard",
            "title": "Dashboard",
            "statusCode": 200,
            "text": "Loaded account dashboard content.",
            "html": "<html><body><main>Loaded account dashboard content.</main></body></html>",
        })
        retrieval = WebRetrievalService(self.settings, browser)
        shell = httpx.Response(
            200,
            text="<html><body><div id='app'></div><script>bootstrap()</script></body></html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "https://app.example/dashboard"),
        )

        with patch("backend.services.web_retrieval.httpx.AsyncClient", return_value=FakeHttpClient(shell)):
            result = asyncio.run(retrieval.browse({"url": "https://app.example/dashboard"}))

        self.assertEqual(result["retrievalMode"], "rendered")
        self.assertIn("Loaded account dashboard", result["text"])

    def test_rendered_browse_returns_visible_dynamic_page_content(self) -> None:
        browser = FakeRenderedBrowser({
            "url": "https://app.example/data",
            "title": "Rendered App",
            "statusCode": 200,
            "text": "Visible dynamic result after JavaScript loaded.",
            "html": "<html><title>Rendered App</title><body><main></main></body></html>",
        })
        retrieval = WebRetrievalService(self.settings, browser)

        result = asyncio.run(retrieval.browse({"url": "https://app.example/data", "mode": "rendered"}))

        self.assertEqual(result["retrievalMode"], "rendered")
        self.assertIn("Visible dynamic result", result["text"])
        self.assertEqual(result["confidence"], "high")

    def test_agent_preserves_generic_retrieved_facts_for_fallback_answers(self) -> None:
        observation = {
            "url": "https://example.gov/notice",
            "text": "Official notice",
            "facts": [{"type": "Article", "headline": "Updated deadline", "datePublished": "2026-05-26"}],
        }

        compact = AgentService.compact_observation({"tool": "browse_url"}, observation)
        fallback = AgentService.deterministic_final_from_transcript(
            "Find the current deadline",
            {},
            [{"action": {"tool": "browse_url"}, "observation": observation}],
        )

        self.assertEqual(compact["structuredFacts"]["retrieved"][0]["headline"], "Updated deadline")
        self.assertIn("Updated deadline", fallback)

    def test_pdf_text_and_image_ocr_diagnostic_are_first_class_browse_results(self) -> None:
        tools = ToolService(self.settings, Storage(self.settings))
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "source.pdf"
            tools.write_pdf(pdf_path, "Official Notice", "The filing date is 30 June.")
            pdf_data = pdf_path.read_bytes()
        retrieval = WebRetrievalService(self.settings, FakeRenderedBrowser())
        pdf_response = httpx.Response(
            200,
            content=pdf_data,
            headers={"content-type": "application/pdf"},
            request=httpx.Request("GET", "https://example.gov/notice.pdf"),
        )
        pdf_result = retrieval.extract_response(pdf_response, 5000)

        self.assertEqual(pdf_result["contentType"], "application/pdf")
        self.assertIn("filing date", pdf_result["text"])

        missing_ocr = self.settings.model_copy(deep=True)
        missing_ocr.tesseract_path = Path(tmp) / "not-installed.exe"
        image_retrieval = WebRetrievalService(missing_ocr, FakeRenderedBrowser())
        image_response = httpx.Response(
            200,
            content=b"not-an-image",
            headers={"content-type": "image/png"},
            request=httpx.Request("GET", "https://example.com/image.png"),
        )
        image_result = image_retrieval.extract_response(image_response, 1000)
        self.assertIn("Tesseract was not found", image_result["error"])

    def test_authenticated_browser_endpoint_never_closes_running_edge(self) -> None:
        with patch.object(app_module.tools.browser_sessions, "edge_running", return_value=True):
            response = self.client.post("/api/browser-session/start")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["blocked"])
        self.assertIn("Close all Microsoft Edge windows", response.json()["message"])

    def test_authenticated_browse_requires_an_active_visible_session(self) -> None:
        sessions = BrowserSessionManager(self.settings)
        retrieval = WebRetrievalService(self.settings, sessions)

        result = asyncio.run(retrieval.browse({"url": "https://account.example/private", "session": "authenticated"}))

        self.assertEqual(result["session"], "authenticated")
        self.assertIn("No authenticated browser session", result["error"])

    def test_direct_code_answer_is_wrapped_in_fenced_block(self) -> None:
        settings = self.settings
        storage = Storage(settings)
        tools = ToolService(settings, storage)
        agent = AgentService(settings, FakeCodeChatModel(), tools)

        result = asyncio.run(agent.run("show a javascript hello world snippet", [], str(settings.root_dir), planning_mode=False))
        self.assertIn("```javascript", result["final"])
        self.assertIn("console.log", result["final"])

    def test_labeled_css_answer_is_fenced(self) -> None:
        raw = "Options\n\nCSS:\n\n.skills {\n\nposition: fixed;\n\nbottom: 16px;\n\n}\n\nDone."
        formatted = AgentService.format_final_answer(raw)
        self.assertIn("```css", formatted)
        self.assertIn(".skills {", formatted)
        self.assertIn("```", formatted)

    def test_auto_plan_turns_on_for_complex_coding_tasks(self) -> None:
        planner = HierarchicalPlanner()
        runtime_plan = planner.plan("/code fix the frontend formatting")
        self.assertTrue(AgentService.should_auto_show_plan("/code fix the frontend formatting", runtime_plan))

        simple_plan = {"allowedTools": ["read_file"]}
        self.assertFalse(AgentService.should_auto_show_plan("what is Vogi?", simple_plan))

    def test_upgrade_uses_vogi_root_and_injects_self_file_map(self) -> None:
        settings = self.settings
        storage = Storage(settings)
        tools = FakeNoWriteToolService(settings, storage)
        fake = FakeUpgradeMustEditModel()
        agent = AgentService(settings, fake, tools)

        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(agent.run("/upgrade make the skills stick to the left bottom", [], tmp, planning_mode=False))

        user_context = fake.message_calls[0][-1]["content"]
        self.assertEqual(Path(result["projectRoot"]).resolve(), settings.root_dir.resolve())
        self.assertIn("Root mode: vogi-self-upgrade", user_context)
        self.assertIn("Frontend/index.html", user_context)
        self.assertIn("Frontend/raw-platform.js", user_context)

    def test_project_mode_injects_opened_project_file_map(self) -> None:
        settings = self.settings
        storage = Storage(settings)
        tools = ToolService(settings, storage)
        fake = FakeContextCaptureModel()
        agent = AgentService(settings, fake, tools)

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "src").mkdir()
            Path(tmp, "src", "app.js").write_text("console.log('project')", encoding="utf-8")
            asyncio.run(agent.run("/code inspect this project", [], tmp, planning_mode=False))

        user_context = fake.messages[-1]["content"]
        self.assertIn("Root mode: opened-project", user_context)
        self.assertIn("src/app.js", user_context)

    def test_upgrade_blocks_snippet_final_until_real_write(self) -> None:
        settings = self.settings
        storage = Storage(settings)
        fake_tools = FakeNoWriteToolService(settings, storage)
        agent = AgentService(settings, FakeUpgradeMustEditModel(), fake_tools)

        result = asyncio.run(agent.run("/upgrade make the skills stick to the left bottom", [], str(settings.root_dir), planning_mode=False))

        self.assertEqual(result["final"], "Edited Vogi.")
        self.assertTrue(any(entry.get("type") == "invalid_final" for entry in result["transcript"]))
        self.assertTrue(any((entry.get("action") or {}).get("tool") == "write_file" for entry in result["transcript"]))

    def test_upgrade_empty_response_reports_incomplete_without_write(self) -> None:
        tools = FakeNoWriteToolService(self.settings, Storage(self.settings))
        agent = AgentService(self.settings, FakeEmptyUpgradeModel(), tools)

        result = asyncio.run(agent.run("/upgrade create standalone project directories", [], str(self.settings.root_dir), planning_mode=False))

        self.assertIn("upgrade is incomplete", result["final"].lower())
        self.assertIn("no vogi files were changed", result["final"].lower())
        self.assertEqual(result["changes"], [])

    def test_upgrade_blocks_memory_tool_detour_and_continues_to_edit(self) -> None:
        tools = FakeNoWriteToolService(self.settings, Storage(self.settings))
        agent = AgentService(self.settings, FakeOutOfScopeUpgradeModel(), tools)

        result = asyncio.run(agent.run("/upgrade automatically save chats and memory", [], str(self.settings.root_dir), planning_mode=False))

        self.assertEqual(result["final"], "Edited source.")
        self.assertNotIn("recall_project", [action["tool"] for action in tools.actions])
        self.assertTrue(any(
            entry.get("type") == "tool"
            and (entry.get("action") or {}).get("tool") == "recall_project"
            and "not available" in str((entry.get("observation") or {}).get("error", ""))
            for entry in result["transcript"]
        ))

    def test_openai_gpt5_decisions_receive_workable_output_budget(self) -> None:
        settings = self.settings.model_copy(deep=True)
        settings.model_provider = "openai"
        settings.agent_model = "gpt-5-mini"
        agent = AgentService(settings, FakeEmptyUpgradeModel(), FakeNoWriteToolService(settings, Storage(settings)))

        self.assertEqual(agent.decision_token_budget(), 6000)

    def test_cloud_rate_limit_falls_back_to_installed_local_model(self) -> None:
        settings = self.settings.model_copy(deep=True)
        settings.model_provider = "openai"
        settings.agent_model = "gpt-5-mini"
        router = ModelRouter(settings)
        router.openai.chat = AsyncMock(side_effect=ModelProviderError("HTTP 429: Too Many Requests"))
        router.ollama.list_models = AsyncMock(return_value=["gemma4:e4b"])
        router.ollama.chat = AsyncMock(return_value={"message": {"content": '{"final": "ok"}'}})

        result = asyncio.run(router.chat([{"role": "user", "content": "test"}], response_format="json"))

        self.assertEqual(result["fallback"]["provider"], "ollama")
        self.assertEqual(result["fallback"]["model"], "gemma4:e4b")
        router.ollama.chat.assert_awaited_once()

    def test_cloud_fallback_is_reused_without_recalling_throttled_provider(self) -> None:
        settings = self.settings.model_copy(deep=True)
        settings.model_provider = "openai"
        settings.agent_model = "gpt-5-mini"
        router = ModelRouter(settings)
        router.openai.chat = AsyncMock(side_effect=ModelProviderError("HTTP 429: Too Many Requests"))
        router.ollama.list_models = AsyncMock(return_value=["gemma4:e4b"])
        router.ollama.chat = AsyncMock(return_value={"message": {"content": '{"final": "ok"}'}})

        asyncio.run(router.chat([{"role": "user", "content": "first"}], response_format="json", timeout=180))
        second = asyncio.run(router.chat([{"role": "user", "content": "second"}], response_format="json", timeout=180))

        router.openai.chat.assert_awaited_once()
        self.assertEqual(router.openai.chat.await_args.kwargs["timeout"], 30)
        self.assertIn("fallback is active", second["fallback"]["reason"].lower())

    def test_provider_failure_returns_final_instead_of_raising(self) -> None:
        tools = FakeNoWriteToolService(self.settings, Storage(self.settings))
        agent = AgentService(self.settings, FakeFailingUpgradeModel(), tools)

        result = asyncio.run(agent.run("/upgrade fix code", [], str(self.settings.root_dir), planning_mode=False))

        self.assertIn("configured model service failed", result["final"].lower())
        self.assertIn("no vogi files were changed", result["final"].lower())

    def test_job_prompt_forces_job_tool_before_questions(self) -> None:
        settings = self.settings
        storage = Storage(settings)
        tools = FakeConsumerToolService(settings, storage)
        model = FakeConsumerModel([
            {"final": "Before I start, a few quick questions about seniority.", "summary": ["asked"], "files": []},
            {"final": "Found React jobs and prepared a short application summary with https://jobs.example/react.", "summary": ["searched jobs"], "files": []},
        ])
        agent = AgentService(settings, model, tools)

        result = asyncio.run(agent.run("Find current remote React developer jobs and prepare an application summary", [], str(settings.root_dir), planning_mode=False))

        self.assertEqual(tools.actions[0]["tool"], "browse_jobs")
        self.assertTrue(any(entry.get("type") == "invalid_final" for entry in result["transcript"]))
        self.assertIn("React jobs", result["final"])

    def test_price_graph_requires_search_and_artifact_before_final(self) -> None:
        settings = self.settings
        storage = Storage(settings)
        tools = FakeConsumerToolService(settings, storage)
        model = FakeConsumerModel([
            {"final": "Cheapest is ₹79900, no file needed.", "summary": ["answered"], "files": []},
            {"action": {"tool": "create_artifact", "args": {"path": "price-graph.md", "format": "md", "content": "| Seller | Price |\n| Example | ₹79900 |"}}, "plan": ["create graph artifact"], "status": "Creating graph artifact."},
            {"final": "Created a lowest-price graph artifact and cited https://shop.example/iphone.", "summary": ["created graph"], "files": ["price-graph.md"]},
        ])
        agent = AgentService(settings, model, tools)
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(agent.run("Compare current iPhone 17 prices in India and create a lowest-price graph", [], tmp, planning_mode=False))
            self.assertTrue(Path(tmp, "price-graph.md").exists())

        self.assertEqual(tools.actions[0]["tool"], "web_search")
        self.assertIn("create_artifact", [action["tool"] for action in tools.actions])
        self.assertTrue(any(entry.get("type") == "invalid_final" for entry in result["transcript"]))

    def test_no_web_access_final_is_blocked_when_web_tools_exist(self) -> None:
        planner = HierarchicalPlanner()
        runtime_plan = planner.plan("Search current GST filing deadline with source URLs")
        reason = AgentService.consumer_final_block_reason(
            "Search current GST filing deadline with source URLs",
            [],
            runtime_plan,
            {"final": "I don't have live web access."},
        )
        self.assertIn("web access", reason)

    def test_file_inspection_claim_requires_file_tool_trace(self) -> None:
        planner = HierarchicalPlanner()
        runtime_plan = planner.plan("Inspect this project and find where skills appears")
        reason = AgentService.consumer_final_block_reason(
            "Inspect this project and find where skills appears",
            [],
            runtime_plan,
            {"final": "I inspected frontend.js and found skills."},
        )
        self.assertIn("file", reason.lower())

    def test_repeated_semantic_web_search_is_blocked(self) -> None:
        runtime_plan = HierarchicalPlanner().plan("Compare current iPhone prices in India")
        action = {"tool": "web_search", "args": {"query": "latest iPhone prices India"}}
        previous = [("web_search", json.dumps({"query": "current iPhone price in India"}, sort_keys=True))]
        reason = AgentService.repeated_action_reason(action, ("web_search", "{}"), previous, {}, runtime_plan)
        self.assertIn("semantic query", reason)

    def test_project_command_tool_is_stored_in_project_scope(self) -> None:
        settings = self.settings
        storage = Storage(settings)
        tools = ToolService(settings, storage)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = asyncio.run(tools.execute({"tool": "create_command_tool", "args": {"name": "list_eval_files", "command": "Get-ChildItem -File"}}, root))
            created = Path(result["path"])
        self.assertIn(".vogi-tools", created.parts)
        self.assertNotIn(".gemma-tools", created.parts)


if __name__ == "__main__":
    unittest.main()
