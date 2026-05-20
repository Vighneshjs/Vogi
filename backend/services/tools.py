from __future__ import annotations

import asyncio
import json
import platform
import re
import shutil
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings
from ..db import Storage
from ..exceptions import ToolExecutionError, ValidationError
from .utils import iso_now, read_json, slugify, trim_output, write_json


class ToolService:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.storage = storage
        self.undo_stack: list[dict[str, Any]] = []

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

    def assert_safe_shell(self, command: str) -> None:
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

    async def run_shell(self, command: str, cwd: str | None, timeout_ms: int, root: Path) -> dict[str, Any]:
        self.assert_safe_shell(command)
        proc = await asyncio.create_subprocess_shell(
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
        }

    async def execute(self, action: dict[str, Any], root: Path) -> Any:
        tool = action.get("tool")
        args = action.get("args") or {}
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
            return [{"name": p.name, "type": "directory" if p.is_dir() else "file" if p.is_file() else "other"} for p in sorted(target.iterdir(), key=lambda item: item.name.lower())]
        if tool == "find_files":
            target = self.normalize_path(args.get("path", "."), root)
            pattern = args.get("pattern") or "*"
            return [str(p) for p in target.rglob(pattern if "*" in pattern else f"*{pattern}*") if p.is_file()][:200]
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
            return await self.run_shell(args.get("command"), args.get("cwd"), int(args.get("timeout_ms") or 20000), root)
        if tool == "create_command_tool":
            return self.create_command_tool(args)
        if tool == "list_command_tools":
            return [read_json(path) for path in self.settings.tools_dir.glob("*.json") if not path.name.endswith(".skill.json")] if self.settings.tools_dir.exists() else []
        if tool == "run_command_tool":
            payload = read_json(self.settings.tools_dir / f"{slugify(args.get('name'))}.json")
            return await self.run_shell(payload["command"], args.get("cwd"), int(args.get("timeout_ms") or 20000), root)
        if tool == "create_schema":
            return self.create_schema(args)
        if tool == "list_schemas":
            return [read_json(path) for path in self.settings.schemas_dir.glob("*.json")] if self.settings.schemas_dir.exists() else []
        if tool == "create_skill":
            return self.create_skill(args)
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
        if tool == "browse_url":
            return await self.browse_url(args)
        if tool == "undo_last_change":
            return self.undo_last_change()
        raise ToolExecutionError(f"Unknown tool: {tool}")

    def search_text(self, args: dict[str, Any], root: Path) -> list[dict[str, Any]]:
        query = str(args.get("query") or "")
        if not query:
            raise ValidationError("search_text query is required.")
        target = self.normalize_path(args.get("path", "."), root)
        results: list[dict[str, Any]] = []
        for path in target.rglob("*"):
            if not path.is_file() or len(results) >= 200:
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

    def write_or_append(self, tool: str, args: dict[str, Any], root: Path) -> dict[str, Any]:
        target = self.normalize_path(args.get("path"), root)
        self.assert_allowed_write(target, root)
        before = self.snapshot(target)
        content = str(args.get("content") or "")
        target.parent.mkdir(parents=True, exist_ok=True)
        if tool == "append_file":
            with target.open("a", encoding="utf-8") as handle:
                handle.write(content)
        else:
            target.write_text(content, encoding="utf-8")
        self.remember_undo(f"{tool} {args.get('path')}", [{"path": str(target), "before": before}])
        return {"written": str(target), "bytes": len(content.encode("utf-8"))}

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

    def create_command_tool(self, args: dict[str, Any]) -> dict[str, Any]:
        name = slugify(args.get("name"))
        self.assert_safe_shell(args.get("command", ""))
        target = self.settings.tools_dir / f"{name}.json"
        before = self.snapshot(target)
        payload = {"name": name, "description": str(args.get("description") or ""), "command": str(args.get("command") or ""), "createdAt": iso_now()}
        write_json(target, payload)
        self.remember_undo(f"create_command_tool {name}", [{"path": str(target), "before": before}])
        return {"created": name, "path": str(target)}

    def create_schema(self, args: dict[str, Any]) -> dict[str, Any]:
        name = slugify(args.get("name"))
        target = self.settings.schemas_dir / f"{name}.json"
        before = self.snapshot(target)
        payload = {"name": name, "description": str(args.get("description") or ""), "schema": args.get("schema") or {}, "createdAt": iso_now()}
        write_json(target, payload)
        self.remember_undo(f"create_schema {name}", [{"path": str(target), "before": before}])
        return {"created": name, "path": str(target)}

    def create_skill(self, args: dict[str, Any]) -> dict[str, Any]:
        name = slugify(args.get("name"))
        target = self.settings.tools_dir / f"{name}.skill.json"
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
        url = str(args.get("url") or "").strip()
        if not re.match(r"^https?://", url, flags=re.I):
            raise ValidationError("browse_url requires an http or https URL.")
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "VogiLocalAgent/2.0"})
        return {
            "url": str(response.url),
            "statusCode": response.status_code,
            "contentType": response.headers.get("content-type", ""),
            "text": trim_output(response.text, int(args.get("max_chars") or 12000)),
        }
