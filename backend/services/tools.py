from __future__ import annotations

import asyncio
import difflib
import json
import platform
import re
import shutil
import sys
import zipfile
from html import escape
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine, text as sql_text

from ..config import Settings
from ..db import Storage
from ..exceptions import ToolExecutionError, ValidationError
from .browser_sessions import BrowserSessionManager
from .capabilities import CapabilityRegistry
from .utils import iso_now, read_json, slugify, trim_output, write_json
from .web_retrieval import WebRetrievalService


class ToolService:
    IGNORED_SCAN_DIRS = {".git", ".vogi-state", ".gemma-tools", ".vogi-tools", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", "reports", "projects"}

    def __init__(self, settings: Settings, storage: Storage, retrieval: WebRetrievalService | None = None) -> None:
        self.settings = settings
        self.storage = storage
        self.undo_stack: list[dict[str, Any]] = []
        self.capabilities = CapabilityRegistry()
        self.browser_sessions = retrieval.browser_sessions if retrieval else BrowserSessionManager(settings)
        self.retrieval = retrieval or WebRetrievalService(settings, self.browser_sessions)

    def normalize_path(self, target: str | None = ".", root: Path | None = None) -> Path:
        base = root or self.settings.root_dir
        raw = Path(target or ".")
        return raw.resolve() if raw.is_absolute() else (base / raw).resolve()

    def snapshot(self, target: Path) -> dict[str, Any]:
        if not target.exists():
            return {"exists": False}
        if target.is_dir():
            return {"exists": True, "type": "directory"}
        return {"exists": True, "type": "file", "content": target.read_text(encoding="utf-8", errors="replace")}

    def remember_undo(self, label: str, paths: list[dict[str, Any]]) -> None:
        self.undo_stack.append({"label": label, "createdAt": iso_now(), "paths": paths})
        del self.undo_stack[:-25]

    def undo_last_change(self) -> dict[str, Any]:
        if not self.undo_stack:
            return {"undone": False, "message": "No undo snapshot is available."}
        item = self.undo_stack.pop()
        for entry in reversed(item["paths"]):
            target = Path(entry["path"])
            before = entry["before"]
            if not before.get("exists"):
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                elif target.exists():
                    target.unlink()
                continue
            if before.get("type") == "directory":
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(before.get("content", ""), encoding="utf-8")
        return {"undone": True, "label": item["label"], "restored": [entry["path"] for entry in item["paths"]]}

    @staticmethod
    def normalize_permission_mode(permission_mode: str | None) -> str:
        return "full" if str(permission_mode or "").strip().lower() == "full" else "safe"

    def assert_safe_shell(self, command: str, permission_mode: str = "safe") -> None:
        text = str(command or "").strip()
        blocked = [
            r"\bformat\b",
            r"\bdiskpart\b",
            r"\bshutdown\b",
            r"\brestart-computer\b",
            r"\bstop-computer\b",
            r"\bremove-item\b[\s\S]*\b-recurse\b[\s\S]*\b-force\b",
            r"\brm\s+-rf\s+(?:/|~|\*|[a-z]:\\)",
            r"\bdel\s+/[fsq]\b",
            r"\bgit\s+reset\s+--hard\b",
            r"\bgit\s+clean\s+-fd\b",
        ]
        if not text:
            raise ValidationError("Shell command cannot be empty.")
        if any(re.search(pattern, text, flags=re.I) for pattern in blocked):
            raise ValidationError("Blocked a destructive or system-level command.")
        if self.normalize_permission_mode(permission_mode) != "full":
            modifies_system = [
                r"\b(?:winget|choco|scoop)\s+install\b",
                r"\b(?:pip|python(?:\.exe)?\s+-m\s+pip)\s+install\b",
                r"\binvoke-webrequest\b[\s\S]*\b-outfile\b",
                r"\bstart-process\b[\s\S]*\b-ver[b]?\s+runas\b",
                r"\bnew-service\b|\bsc(?:\.exe)?\s+create\b|\b--service-install\b",
                r"\bnew-netfirewallrule\b",
            ]
            if any(re.search(pattern, text, flags=re.I) for pattern in modifies_system):
                raise ValidationError("This command installs software or changes system state. Select Full Access and run it again.")

    async def run_shell(self, command: str, cwd: str | None, timeout_ms: int, root: Path, permission_mode: str = "safe") -> dict[str, Any]:
        permission_mode = self.normalize_permission_mode(permission_mode)
        self.assert_safe_shell(command, permission_mode)
        proc = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
            cwd=str(self.normalize_path(cwd, root)),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=min(max(timeout_ms / 1000, 1), 120))
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise ToolExecutionError("Command timed out.") from exc
        return {
            "stdout": trim_output(stdout.decode(errors="replace")),
            "stderr": trim_output(stderr.decode(errors="replace")),
            "exitCode": proc.returncode,
            "shell": "powershell",
            "permissionMode": permission_mode,
        }

    async def execute(self, action: dict[str, Any], root: Path, permission_mode: str = "safe") -> Any:
        tool = action.get("tool")
        args = action.get("args") or {}
        permission_mode = self.normalize_permission_mode(permission_mode)
        if tool == "get_system_info":
            return {
                "platform": platform.system(),
                "release": platform.release(),
                "arch": platform.machine(),
                "agentRoot": str(self.settings.root_dir),
                "projectRoot": str(root),
                "python": platform.python_version(),
                "storage": self.storage.mode,
            }
        if tool == "list_dir":
            target = self.normalize_path(args.get("path", "."), root)
            return [{"name": p.name, "type": "directory" if p.is_dir() else "file" if p.is_file() else "other"} for p in sorted(target.iterdir(), key=lambda item: item.name.lower()) if p.name not in self.IGNORED_SCAN_DIRS]
        if tool == "find_files":
            target = self.normalize_path(args.get("path", "."), root)
            pattern = args.get("pattern") or "*"
            return [str(p) for p in target.rglob(pattern if "*" in pattern else f"*{pattern}*") if p.is_file() and not self.is_ignored_scan_path(p, root)][:200]
        if tool == "search_text":
            return self.search_text(args, root)
        if tool == "read_file":
            target = self.normalize_path(args.get("path"), root)
            content = target.read_text(encoding="utf-8", errors="replace")
            
            start_line = args.get("start_line")
            end_line = args.get("end_line")
            
            if start_line is not None or end_line is not None:
                lines = content.splitlines()
                start = max(0, int(start_line or 1) - 1)
                end = int(end_line or len(lines))
                content = "\n".join(lines[start:end])
                return f"Lines {start+1}-{end} of {target.name}:\n\n{content}"
            
            return trim_output(content, int(args.get("max_chars") or 8000))
        if tool in {"write_file", "append_file"}:
            return self.write_or_append(tool, args, root)
        if tool == "make_dir":
            target = self.normalize_path(args.get("path"), root)
            before = self.snapshot(target)
            target.mkdir(parents=True, exist_ok=True)
            self.remember_undo(f"make_dir {args.get('path')}", [{"path": str(target), "before": before}])
            return {"created": str(target)}
        if tool == "run_shell":
            return await self.run_shell(args.get("command"), args.get("cwd"), int(args.get("timeout_ms") or 20000), root, permission_mode)
        if tool == "install_package":
            return await self.install_package(args, root, permission_mode)
        if tool == "database_query":
            return self.database_query(args, permission_mode)
        if tool == "http_request":
            return await self.http_request(args, permission_mode)
        if tool == "create_command_tool":
            return self.create_command_tool(args, root)
        if tool == "list_command_tools":
            return self.list_command_tools(root)
        if tool == "run_command_tool":
            payload = self.read_command_tool(args.get("name"), root)
            return await self.run_shell(payload["command"], args.get("cwd"), int(args.get("timeout_ms") or 20000), root, permission_mode)
        if tool == "create_schema":
            return self.create_schema(args, root)
        if tool == "list_schemas":
            return [read_json(path) for path in self.settings.schemas_dir.glob("*.json")] if self.settings.schemas_dir.exists() else []
        if tool == "create_skill":
            return self.create_skill(args, root)
        if tool == "list_skills":
            file_skills = [read_json(path) for path in self.settings.tools_dir.glob("*.skill.json")] if self.settings.tools_dir.exists() else []
            return {"database": self.storage.list_skills(), "files": file_skills}
        if tool == "remember_project":
            project_id = str(args.get("project_id") or args.get("projectId") or "")
            if not project_id:
                raise ValidationError("remember_project requires project_id.")
            return self.storage.save_memory(project_id, args)
        if tool == "recall_project":
            project_id = str(args.get("project_id") or args.get("projectId") or "")
            if not project_id:
                raise ValidationError("recall_project requires project_id.")
            return self.storage.list_memories(project_id)
        if tool == "web_search":
            return await self.web_search(args)
        if tool == "browse_url":
            return await self.browse_url(args)
        if tool == "browse_jobs":
            return await self.browse_jobs(args)
        if tool == "prepare_job_application":
            return self.prepare_job_application(args, root)
        if tool == "create_artifact":
            return self.create_artifact(args, root)
        if tool == "create_slides":
            return self.create_slides(args, root)
        if tool == "context_window_report":
            return self.context_window_report(args)
        if tool == "undo_last_change":
            return self.undo_last_change()
        if tool == "ask_user":
            question = str(args.get("question") or "").strip()
            if not question:
                raise ValidationError("ask_user requires a 'question'.")
            return {"question": question, "waiting_for_user": True}
        raise ToolExecutionError(f"Unknown tool: {tool}")

    def search_text(self, args: dict[str, Any], root: Path) -> list[dict[str, Any]]:
        query = str(args.get("query") or "")
        if not query:
            raise ValidationError("search_text query is required.")
        target = self.normalize_path(args.get("path", "."), root)
        results: list[dict[str, Any]] = []
        for path in target.rglob("*"):
            if not path.is_file() or self.is_ignored_scan_path(path, root) or len(results) >= 200:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if query in line:
                    results.append({"path": str(path), "lineNumber": number, "line": trim_output(line, 500)})
                    if len(results) >= 200:
                        break
        return results

    def is_ignored_scan_path(self, path: Path, scan_root: Path) -> bool:
        try:
            relative_parts = path.relative_to(scan_root).parts
        except ValueError:
            relative_parts = path.parts
        return any(part in self.IGNORED_SCAN_DIRS for part in relative_parts)

    async def install_package(self, args: dict[str, Any], root: Path, permission_mode: str) -> dict[str, Any]:
        if self.normalize_permission_mode(permission_mode) != "full":
            raise ValidationError("Installing packages requires Full Access.")
        manager = str(args.get("manager") or "winget").strip().lower()
        package = str(args.get("package") or "").strip()
        if not package or not re.match(r"^[A-Za-z0-9_.@+:-]+$", package):
            raise ValidationError("install_package requires a valid package identifier.")
        if manager == "winget":
            scope = str(args.get("scope") or "").strip().lower()
            scope_flag = f" --scope {scope}" if scope in {"user", "machine"} else ""
            command = (
                f"winget install --id '{package}' --exact --disable-interactivity "
                f"--accept-source-agreements --accept-package-agreements{scope_flag}"
            )
        elif manager == "pip":
            command = f"& '{sys.executable}' -m pip install '{package}'"
        else:
            raise ValidationError("install_package manager must be winget or pip.")
        result = await self.run_shell(command, args.get("cwd"), int(args.get("timeout_ms") or 120000), root, "full")
        combined = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".lower()
        result.update({
            "manager": manager,
            "package": package,
            "installed": result.get("exitCode") == 0,
            "requiresElevation": result.get("exitCode") != 0 and any(marker in combined for marker in ["administrator", "elevation", "access is denied", "requires admin"]),
        })
        return result

    def database_query(self, args: dict[str, Any], permission_mode: str) -> dict[str, Any]:
        statement = str(args.get("sql") or args.get("query") or "").strip()
        connection_url = str(args.get("connectionUrl") or self.settings.database_url or "").strip()
        if not statement:
            raise ValidationError("database_query requires sql.")
        if not connection_url:
            raise ValidationError("database_query requires connectionUrl or configured database_url.")
        lowered = re.sub(r"^\s*(?:--[^\n]*\n\s*)*", "", statement).lower()
        if self.normalize_permission_mode(permission_mode) != "full" and not re.match(r"^(select|with|show|explain|pragma)\b", lowered):
            raise ValidationError("Safe Mode permits only read-only database queries. Select Full Access for data changes.")
        if re.search(r"\b(drop\s+database|alter\s+system|truncate\s+table)\b", lowered):
            raise ValidationError("Blocked destructive database administration statement.")
        engine = create_engine(connection_url, pool_pre_ping=True)
        try:
            with engine.begin() as connection:
                cursor = connection.execute(sql_text(statement), args.get("params") or {})
                rows = [dict(row._mapping) for row in cursor.fetchmany(100)] if cursor.returns_rows else []
                return {
                    "ok": True,
                    "readOnly": bool(re.match(r"^(select|with|show|explain|pragma)\b", lowered)),
                    "columns": list(cursor.keys()) if cursor.returns_rows else [],
                    "rows": rows,
                    "rowCount": len(rows) if cursor.returns_rows else cursor.rowcount,
                    "truncated": cursor.returns_rows and len(rows) >= 100,
                }
        finally:
            engine.dispose()

    async def http_request(self, args: dict[str, Any], permission_mode: str) -> dict[str, Any]:
        url = str(args.get("url") or "").strip()
        method = str(args.get("method") or "GET").strip().upper()
        if not re.match(r"^https?://", url, flags=re.I):
            raise ValidationError("http_request requires an http or https URL.")
        if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValidationError("Unsupported HTTP method.")
        if method not in {"GET", "HEAD"} and self.normalize_permission_mode(permission_mode) != "full":
            raise ValidationError("Safe Mode permits only GET and HEAD requests. Select Full Access for state-changing HTTP requests.")
        headers = {str(key): str(value) for key, value in (args.get("headers") or {}).items()}
        async with httpx.AsyncClient(timeout=min(max(int(args.get("timeout_ms") or 30000) / 1000, 1), 120), follow_redirects=True) as client:
            response = await client.request(method, url, headers=headers, json=args.get("json"), content=args.get("body"))
        return {
            "url": str(response.url),
            "method": method,
            "statusCode": response.status_code,
            "contentType": response.headers.get("content-type", ""),
            "text": trim_output(response.text, int(args.get("max_chars") or 12000)),
        }

    def write_or_append(self, tool: str, args: dict[str, Any], root: Path) -> dict[str, Any]:
        target = self.normalize_path(args.get("path"), root)
        self.assert_allowed_write(target, root)
        before = self.snapshot(target)
        content = str(args.get("content") or "")
        before_text = before.get("content") if before and before.get("type") == "file" else ""
        target.parent.mkdir(parents=True, exist_ok=True)
        if tool == "append_file":
            with target.open("a", encoding="utf-8") as handle:
                handle.write(content)
            after_text = f"{before_text}{content}"
        else:
            target.write_text(content, encoding="utf-8")
            after_text = content
        self.remember_undo(f"{tool} {args.get('path')}", [{"path": str(target), "before": before}])
        delta = self.line_delta(before_text, after_text)
        return {
            "written": str(target),
            "path": str(target),
            "bytes": len(content.encode("utf-8")),
            "additions": delta["additions"],
            "deletions": delta["deletions"],
            "changed": delta["additions"] > 0 or delta["deletions"] > 0,
        }

    @staticmethod
    def line_delta(before: str, after: str) -> dict[str, int]:
        additions = 0
        deletions = 0
        for opcode, i1, i2, j1, j2 in difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines()).get_opcodes():
            if opcode in {"replace", "delete"}:
                deletions += i2 - i1
            if opcode in {"replace", "insert"}:
                additions += j2 - j1
        return {"additions": additions, "deletions": deletions}

    def assert_allowed_write(self, target: Path, root: Path) -> None:
        resolved = target.resolve()
        agent_root = self.settings.root_dir.resolve()
        allowed_roots = [
            agent_root / "vogi_agent",
            agent_root / "backend",
            agent_root / "Frontend",
            agent_root / "scripts",
            agent_root / ".gemma-tools",
            root.resolve(),
        ]
        if any(resolved == allowed.resolve() or allowed.resolve() in resolved.parents for allowed in allowed_roots):
            return
        raise ValidationError(f"Write blocked outside allowed project/app roots: {resolved}")

    def project_tools_dir(self, root: Path) -> Path:
        if root.resolve() == self.settings.root_dir.resolve():
            return self.settings.tools_dir
        return root.resolve() / ".vogi-tools"

    def list_command_tools(self, root: Path) -> list[dict[str, Any]]:
        dirs = [self.project_tools_dir(root)]
        if root.resolve() != self.settings.root_dir.resolve():
            dirs.append(self.settings.tools_dir)
        items: list[dict[str, Any]] = []
        for directory in dirs:
            if not directory.exists():
                continue
            items.extend(read_json(path) for path in directory.glob("*.json") if not path.name.endswith(".skill.json"))
        return items

    def read_command_tool(self, name: Any, root: Path) -> dict[str, Any]:
        filename = f"{slugify(name)}.json"
        candidates = [self.project_tools_dir(root) / filename, self.settings.tools_dir / filename]
        for path in candidates:
            if path.exists():
                return read_json(path)
        raise ValidationError(f"Command tool not found: {name}")

    def create_command_tool(self, args: dict[str, Any], root: Path) -> dict[str, Any]:
        name = slugify(args.get("name"))
        self.assert_safe_shell(args.get("command", ""), "full")
        target = self.project_tools_dir(root) / f"{name}.json"
        self.assert_allowed_write(target, root)
        before = self.snapshot(target)
        payload = {"name": name, "description": str(args.get("description") or ""), "command": str(args.get("command") or ""), "createdAt": iso_now()}
        write_json(target, payload)
        self.remember_undo(f"create_command_tool {name}", [{"path": str(target), "before": before}])
        return {"created": name, "path": str(target)}

    def create_schema(self, args: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
        name = slugify(args.get("name"))
        target = (root.resolve() / ".vogi-tools" / "schemas" / f"{name}.json") if root and root.resolve() != self.settings.root_dir.resolve() else self.settings.schemas_dir / f"{name}.json"
        if root:
            self.assert_allowed_write(target, root)
        before = self.snapshot(target)
        payload = {"name": name, "description": str(args.get("description") or ""), "schema": args.get("schema") or {}, "createdAt": iso_now()}
        write_json(target, payload)
        self.remember_undo(f"create_schema {name}", [{"path": str(target), "before": before}])
        return {"created": name, "path": str(target)}

    def create_skill(self, args: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
        name = slugify(args.get("name"))
        target = ((root.resolve() / ".vogi-tools") if root and root.resolve() != self.settings.root_dir.resolve() else self.settings.tools_dir) / f"{name}.skill.json"
        if root:
            self.assert_allowed_write(target, root)
        before = self.snapshot(target)
        payload = {
            "name": name,
            "description": str(args.get("description") or ""),
            "instructions": str(args.get("instructions") or ""),
            "tools": args.get("tools") or [],
            "createdAt": iso_now(),
        }
        self.storage.save_skill(payload)
        write_json(target, payload)
        self.remember_undo(f"create_skill {name}", [{"path": str(target), "before": before}])
        return {"created": name, "path": str(target), "skill": payload}

    async def browse_url(self, args: dict[str, Any]) -> dict[str, Any]:
        return await self.retrieval.browse(args)

    async def web_search(self, args: dict[str, Any]) -> dict[str, Any]:
        return await self.retrieval.search(args)

    async def browse_jobs(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "frontend developer").strip()
        location = str(args.get("location") or "remote").strip()
        max_results = min(max(int(args.get("max_results") or 8), 1), 20)
        searches = [
            f"https://remoteok.com/remote-{slugify(query).replace('-', '-')}-jobs",
            f"https://duckduckgo.com/html/?q={query.replace(' ', '+')}+{location.replace(' ', '+')}+jobs",
            f"https://duckduckgo.com/html/?q=site%3Awellfound.com+{query.replace(' ', '+')}+{location.replace(' ', '+')}",
            f"https://duckduckgo.com/html/?q=site%3Alinkedin.com%2Fjobs+{query.replace(' ', '+')}+{location.replace(' ', '+')}",
        ]
        listings: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "VogiLocalAgent/3.0"}) as client:
            for url in searches:
                try:
                    response = await client.get(url)
                    text = response.text
                except Exception:
                    continue
                for href, label in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, flags=re.I | re.S):
                    clean_label = re.sub(r"<[^>]+>", " ", label)
                    clean_label = re.sub(r"\s+", " ", clean_label).strip()
                    if not clean_label or len(clean_label) < 8:
                        continue
                    haystack = clean_label.lower()
                    if not any(term in haystack for term in ["front", "react", "developer", "engineer", "javascript", "typescript", "ui", "software"]):
                        continue
                    absolute = href
                    redirect = re.search(r"[?&]uddg=([^&]+)", absolute.replace("&amp;", "&"))
                    if redirect:
                        try:
                            from urllib.parse import unquote
                            absolute = unquote(redirect.group(1))
                        except Exception:
                            pass
                    if href.startswith("/"):
                        origin = re.match(r"^(https?://[^/]+)", url)
                        absolute = f"{origin.group(1)}{href}" if origin else href
                    company = ""
                    title = clean_label[:160]
                    split = re.split(r"\s[-|•]\s", clean_label, maxsplit=1)
                    if len(split) == 2:
                        title, company = split[0][:120], split[1][:120]
                    listings.append({
                        "title": title,
                        "company": company,
                        "location": location,
                        "url": absolute,
                        "source": url,
                        "snippet": clean_label[:240],
                    })
                    if len(listings) >= max_results:
                        break
                if len(listings) >= max_results:
                    break
        if not listings:
            listings.append({
                "title": f"{query.title()} search fallback",
                "company": "",
                "location": location,
                "url": f"https://duckduckgo.com/html/?q={query.replace(' ', '+')}+{location.replace(' ', '+')}+jobs",
                "source": "search-fallback",
                "snippet": "No normalized listing could be extracted from public pages; use this search URL to review live listings manually.",
            })
        return {
            "query": query,
            "location": location,
            "results": listings[:max_results],
            "note": "Vogi can prepare application materials, but external submission requires explicit user confirmation.",
        }

    def create_artifact(self, args: dict[str, Any], root: Path) -> dict[str, Any]:
        path = str(args.get("path") or "").strip()
        content = str(args.get("content") or "")
        if not path:
            raise ValidationError("create_artifact requires path.")
        target = self.normalize_path(path, root)
        self.assert_allowed_write(target, root)
        before = self.snapshot(target)
        fmt = str(args.get("format") or target.suffix.lstrip(".") or "md").lower()
        title = str(args.get("title") or target.stem.replace("-", " ").title())
        target.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "docx" or target.suffix.lower() == ".docx":
            self.write_docx(target, title, content)
        elif fmt == "pdf" or target.suffix.lower() == ".pdf":
            self.write_pdf(target, title, content)
        elif fmt in {"html", "slides-html"} or target.suffix.lower() == ".html":
            target.write_text(self.render_html(title, content, slides=fmt == "slides-html"), encoding="utf-8")
        elif fmt == "txt" or target.suffix.lower() == ".txt":
            target.write_text(content, encoding="utf-8")
        else:
            target.write_text(f"# {title}\n\n{content}".strip() + "\n", encoding="utf-8")
        self.remember_undo(f"create_artifact {path}", [{"path": str(target), "before": before}])
        return {"created": str(target), "format": fmt, "bytes": target.stat().st_size}

    def create_slides(self, args: dict[str, Any], root: Path) -> dict[str, Any]:
        path = str(args.get("path") or "reports/vogi-slides.html").strip()
        target = self.normalize_path(path, root)
        self.assert_allowed_write(target, root)
        before = self.snapshot(target)
        slides = args.get("slides") or []
        title = str(args.get("title") or "Vogi Presentation")
        html_sections = []
        outline = {"title": title, "slides": []}
        for index, slide in enumerate(slides, start=1):
            slide_title = str(slide.get("title") or f"Slide {index}")
            bullets = slide.get("bullets") or slide.get("points") or []
            body = str(slide.get("body") or "")
            bullet_html = "".join(f"<li>{escape(str(item))}</li>" for item in bullets)
            html_sections.append(f"<section><h1>{escape(slide_title)}</h1><p>{escape(body)}</p><ul>{bullet_html}</ul></section>")
            outline["slides"].append({"title": slide_title, "body": body, "bullets": bullets})
        target.parent.mkdir(parents=True, exist_ok=True)
        html = self.render_html(title, "\n".join(html_sections), raw_body=True, slides=True)
        target.write_text(html, encoding="utf-8")
        outline_path = target.with_suffix(".slides.json")
        outline_before = self.snapshot(outline_path)
        outline_path.write_text(json.dumps(outline, indent=2), encoding="utf-8")
        self.remember_undo(f"create_slides {path}", [{"path": str(target), "before": before}, {"path": str(outline_path), "before": outline_before}])
        return {"created": str(target), "outline": str(outline_path), "slideCount": len(slides)}

    def prepare_job_application(self, args: dict[str, Any], root: Path) -> dict[str, Any]:
        resume_path = str(args.get("resume_path") or args.get("resumePath") or "").strip()
        if not resume_path:
            raise ValidationError("prepare_job_application requires resume_path.")
        resume = self.normalize_path(resume_path, root)
        if not resume.exists() or not resume.is_file():
            raise ValidationError(f"Resume file not found: {resume}")
        output_dir = self.normalize_path(args.get("output_dir") or "reports/job-application", root)
        self.assert_allowed_write(output_dir, root)
        job = args.get("job") or {}
        title = str(job.get("title") or "Frontend Developer")
        company = str(job.get("company") or job.get("source") or "Target Company")
        cover_letter = str(args.get("cover_letter") or "")
        if not cover_letter:
            cover_letter = (
                f"Dear Hiring Team,\n\n"
                f"I am applying for the {title} role at {company}. My resume is attached for your review. "
                f"I would be glad to discuss how my frontend development experience can contribute to your team.\n\n"
                f"Best regards"
            )
        before_dir = self.snapshot(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        copied_resume = output_dir / resume.name
        before_resume = self.snapshot(copied_resume)
        shutil.copy2(resume, copied_resume)
        letter_path = output_dir / "cover-letter.md"
        before_letter = self.snapshot(letter_path)
        letter_path.write_text(f"# Cover Letter\n\n{cover_letter}\n", encoding="utf-8")
        manifest_path = output_dir / "application.json"
        before_manifest = self.snapshot(manifest_path)
        manifest_path.write_text(json.dumps({"job": job, "resume": str(copied_resume), "coverLetter": str(letter_path), "createdAt": iso_now(), "requiresUserSubmitConfirmation": True}, indent=2), encoding="utf-8")
        self.remember_undo(
            "prepare_job_application",
            [
                {"path": str(output_dir), "before": before_dir},
                {"path": str(copied_resume), "before": before_resume},
                {"path": str(letter_path), "before": before_letter},
                {"path": str(manifest_path), "before": before_manifest},
            ],
        )
        return {"packet": str(output_dir), "resume": str(copied_resume), "coverLetter": str(letter_path), "manifest": str(manifest_path), "submitted": False}

    def context_window_report(self, args: dict[str, Any]) -> dict[str, Any]:
        task = str(args.get("task") or "")
        history = args.get("history") or []
        text = task + "\n" + json.dumps(history, ensure_ascii=False)[:200000]
        approx_tokens = max(1, len(text) // 4)
        level = "ok"
        if approx_tokens > 24000:
            level = "compress-now"
        elif approx_tokens > 12000:
            level = "watch"
        return {
            "approxTokens": approx_tokens,
            "level": level,
            "message": "Context is compact." if level == "ok" else "Context is growing; summarize older tool outputs and prefer targeted reads.",
            "recommendedActions": ["Use line ranges for large files", "Summarize long logs", "Keep final task state in project memory"],
        }

    @staticmethod
    def render_html(title: str, content: str, raw_body: bool = False, slides: bool = False) -> str:
        body = content if raw_body else "<p>" + escape(content).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
        slide_css = "section{min-height:100vh;display:flex;flex-direction:column;justify-content:center;padding:8vw;border-bottom:1px solid #ddd}h1{font-size:44px}" if slides else ""
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;line-height:1.55;margin:0;color:#172033;background:#f7f7f4}}
main{{max-width:880px;margin:0 auto;padding:48px 24px;background:white;min-height:100vh}}
h1,h2{{color:#111827}} {slide_css}
</style>
</head>
<body><main>{body}</main></body>
</html>
"""

    @staticmethod
    def write_docx(target: Path, title: str, content: str) -> None:
        paragraphs = [title, *[part.strip() for part in content.splitlines() if part.strip()]]
        paragraph_xml = "".join(f"<w:p><w:r><w:t>{escape(p)}</w:t></w:r></w:p>" for p in paragraphs)
        document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{paragraph_xml}<w:sectPr/></w:body></w:document>"""
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as docx:
            docx.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>""")
            docx.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>""")
            docx.writestr("word/document.xml", document_xml)

    @staticmethod
    def write_pdf(target: Path, title: str, content: str) -> None:
        lines = [title, "", *content.splitlines()]
        commands = ["BT", "/F1 12 Tf", "72 760 Td"]
        first = True
        for line in lines[:48]:
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:95]
            if first:
                commands.append(f"({safe}) Tj")
                first = False
            else:
                commands.append(f"0 -16 Td ({safe}) Tj")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", errors="replace")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        ]
        pdf = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for idx, obj in enumerate(objects, start=1):
            offsets.append(len(pdf))
            pdf.extend(f"{idx} 0 obj\n".encode())
            pdf.extend(obj)
            pdf.extend(b"\nendobj\n")
        xref = len(pdf)
        pdf.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
        for offset in offsets[1:]:
            pdf.extend(f"{offset:010d} 00000 n \n".encode())
        pdf.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
        target.write_bytes(pdf)
