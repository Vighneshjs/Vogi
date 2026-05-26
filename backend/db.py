from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, create_engine, select, text, delete
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .config import Settings
from .services.capabilities import CapabilityRegistry
from .services.utils import slugify


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now().isoformat()


class Base(DeclarativeBase):
    pass


class ProjectRecord(Base):
    __tablename__ = "vogi_projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(240), default="New Project")
    root_path: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ChatRecord(Base):
    __tablename__ = "vogi_chats"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("vogi_projects.id"))
    title: Mapped[str] = mapped_column(String(240), default="New chat")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MemoryRecord(Base):
    __tablename__ = "vogi_memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("vogi_projects.id"))
    kind: Mapped[str] = mapped_column(String(80), default="note")
    key: Mapped[str] = mapped_column(String(240), default="")
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SkillRecord(Base):
    __tablename__ = "vogi_skills"

    name: Mapped[str] = mapped_column(String(120), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class JsonStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.write({"projects": {}, "chats": {}, "memories": {}, "skills": {}, "uploads": {}})

    def read(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            backup = self.path.with_suffix(f".corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}.json")
            self.path.replace(backup)
            data = {}
        for key in ["projects", "chats", "memories", "skills", "uploads"]:
            data.setdefault(key, {})
        if not self.path.exists():
            self.write(data)
        return data

    def write(self, payload: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


BUILTIN_SKILLS: list[dict[str, Any]] = [
    {
        "name": "upgrade",
        "trigger": "/upgrade",
        "description": "Inspect and improve Vogi's own backend, frontend, tools, or skills.",
        "instructions": "Use only when explicitly requested. Inspect relevant files before editing. Keep changes scoped and undoable.",
        "tools": ["read_file", "search_text", "write_file", "append_file", "run_shell", "create_skill", "list_skills"],
        "examples": ["/upgrade improve the skills list"],
        "builtin": True,
    },
    {
        "name": "web_browse",
        "trigger": "/web",
        "description": "Open URLs and summarize online pages.",
        "instructions": "Use browse_url and cite the URL in the answer.",
        "tools": ["browse_url"],
        "examples": ["/web https://example.com"],
        "builtin": True,
    },
    {
        "name": "code_analysis",
        "trigger": "/code",
        "description": "Search, read, explain, edit, and test local code.",
        "instructions": "Search first, read relevant files, then make small focused edits.",
        "tools": ["find_files", "search_text", "read_file", "write_file", "run_shell"],
        "examples": ["/code find where projects are stored"],
        "builtin": True,
    },
    {
        "name": "tool_builder",
        "trigger": "/tool",
        "description": "Create reusable command tools and schemas.",
        "instructions": "Create command tools only for safe repeatable actions.",
        "tools": ["create_command_tool", "create_schema", "list_command_tools", "list_schemas"],
        "examples": ["/tool create a test runner"],
        "builtin": True,
    },
    {
        "name": "project_memory",
        "trigger": "/memory",
        "description": "Store and recall project-specific memories.",
        "instructions": "Save durable project facts and recall them before work.",
        "tools": ["remember_project", "recall_project"],
        "examples": ["/memory remember this project uses FastAPI"],
        "builtin": True,
    },
    {
        "name": "file_ops",
        "trigger": "/files",
        "description": "List, search, read, write, and undo local files.",
        "instructions": "Prefer narrow file operations and keep undo snapshots.",
        "tools": ["list_dir", "find_files", "search_text", "read_file", "write_file", "append_file", "undo_last_change"],
        "examples": ["/files read package.json"],
        "builtin": True,
    },
    {
        "name": "shell_runner",
        "trigger": "/shell",
        "description": "Run safe local shell commands.",
        "instructions": "Run non-destructive commands and report stdout/stderr.",
        "tools": ["run_shell"],
        "examples": ["/shell run tests"],
        "builtin": True,
    },
]

for capability_skill in CapabilityRegistry().public_skills():
    if not any(existing["name"] == capability_skill["name"] for existing in BUILTIN_SKILLS):
        BUILTIN_SKILLS.append(capability_skill)


class Storage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = None
        self.json_store = JsonStore(settings.state_dir / "state.json")
        try:
            self._ensure_postgres_database()
            self.engine = create_engine(settings.database_url, pool_pre_ping=True)
            Base.metadata.create_all(self.engine)
        except Exception:
            self.engine = None
        self.ensure_defaults()

    @property
    def mode(self) -> str:
        return "postgres" if self.engine is not None else "json"

    def _ensure_postgres_database(self) -> None:
        if not self.settings.database_url.startswith("postgresql"):
            return
        url = make_url(self.settings.database_url)
        database = (url.database or "").strip()
        if not database or database in {"postgres", "template1"}:
            return
        admin_engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT", pool_pre_ping=True)
        with admin_engine.connect() as connection:
            exists = connection.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database}).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{database.replace(chr(34), chr(34) * 2)}"'))
        admin_engine.dispose()

    def ensure_defaults(self) -> None:
        project = self.ensure_default_project()
        self.ensure_default_chat(project["id"])
        for skill in BUILTIN_SKILLS:
            self.save_skill(skill)

    def ensure_default_project(self) -> dict[str, Any]:
        projects = self.list_projects()
        system = next((project for project in projects if project.get("kind") == "system"), None)
        if system:
            return system
        legacy_system = next(
            (
                project
                for project in projects
                if Path(project.get("rootPath") or "").resolve() == self.settings.root_dir.resolve()
                and project.get("name") == self.settings.root_dir.name
            ),
            None,
        )
        if legacy_system:
            return self.save_project({**legacy_system, "kind": "system"})
        return self.save_project({"name": self.settings.root_dir.name, "rootPath": str(self.settings.root_dir), "kind": "system"})

    def ensure_default_chat(self, project_id: str) -> dict[str, Any]:
        chats = self.list_chats(project_id)
        if chats:
            return chats[0]
        return self.save_chat(project_id, {"title": "Vogi", "messages": [], "plan": [], "trace": []})

    def save_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": str(payload.get("id") or uuid.uuid4()),
            "name": str(payload.get("name") or "New Project"),
            "rootPath": str(payload.get("rootPath") or self.settings.root_dir),
            "kind": str(payload.get("kind") or "external"),
            "createdAt": payload.get("createdAt") or iso_now(),
            "updatedAt": iso_now(),
        }
        if self.engine is not None:
            try:
                with Session(self.engine) as session:
                    record = session.get(ProjectRecord, item["id"]) or ProjectRecord(id=item["id"], created_at=now())
                    record.name = item["name"]
                    record.root_path = item["rootPath"]
                    record.payload = item
                    record.updated_at = now()
                    session.add(record)
                    session.commit()
                return item
            except SQLAlchemyError:
                pass
        data = self.json_store.read()
        data["projects"][item["id"]] = item
        self.json_store.write(data)
        return item

    def create_project(self, name: str, root_path: str | None = None) -> dict[str, Any]:
        project_id = str(uuid.uuid4())
        if root_path:
            return self.save_project({
                "id": project_id,
                "name": name,
                "rootPath": str(Path(root_path).resolve()),
                "kind": "external",
            })
        root = self.settings.projects_dir / f"{slugify(name)}-{project_id[:8]}"
        root.mkdir(parents=True, exist_ok=False)
        return self.save_project({
            "id": project_id,
            "name": name,
            "rootPath": str(root),
            "kind": "managed",
        })

    def list_projects(self) -> list[dict[str, Any]]:
        if self.engine is not None:
            try:
                with Session(self.engine) as session:
                    rows = session.scalars(select(ProjectRecord).order_by(ProjectRecord.updated_at.desc())).all()
                    return [row.payload for row in rows]
            except SQLAlchemyError:
                pass
        return sorted(self.json_store.read()["projects"].values(), key=lambda item: item.get("updatedAt", ""), reverse=True)

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        for project in self.list_projects():
            if project["id"] == project_id:
                return project
        return None

    def delete_project(self, project_id: str) -> None:
        if self.engine is not None:
            try:
                with Session(self.engine) as session:
                    session.execute(delete(MemoryRecord).where(MemoryRecord.project_id == project_id))
                    session.execute(delete(ChatRecord).where(ChatRecord.project_id == project_id))
                    record = session.get(ProjectRecord, project_id)
                    if record:
                        session.delete(record)
                    session.commit()
            except SQLAlchemyError:
                pass
        data = self.json_store.read()
        if project_id in data["projects"]:
            del data["projects"][project_id]
            data["chats"] = {k: v for k, v in data["chats"].items() if v.get("projectId") != project_id}
            data["memories"] = {k: v for k, v in data["memories"].items() if v.get("projectId") != project_id}
            self.json_store.write(data)

    def save_chat(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": str(payload.get("id") or uuid.uuid4()),
            "projectId": project_id,
            "title": str(payload.get("title") or "New chat"),
            "messages": payload.get("messages") or [],
            "plan": payload.get("plan") or [],
            "trace": payload.get("trace") or [],
            "createdAt": payload.get("createdAt") or iso_now(),
            "updatedAt": iso_now(),
        }
        if self.engine is not None:
            try:
                with Session(self.engine) as session:
                    record = session.get(ChatRecord, item["id"]) or ChatRecord(id=item["id"], project_id=project_id, created_at=now())
                    record.project_id = project_id
                    record.title = item["title"]
                    record.payload = item
                    record.updated_at = now()
                    session.add(record)
                    session.commit()
                return item
            except SQLAlchemyError:
                pass
        data = self.json_store.read()
        data["chats"][item["id"]] = item
        self.json_store.write(data)
        return item

    def list_chats(self, project_id: str) -> list[dict[str, Any]]:
        if self.engine is not None:
            try:
                with Session(self.engine) as session:
                    rows = session.scalars(select(ChatRecord).where(ChatRecord.project_id == project_id).order_by(ChatRecord.updated_at.desc())).all()
                    return [row.payload for row in rows]
            except SQLAlchemyError:
                pass
        return sorted(
            [item for item in self.json_store.read()["chats"].values() if item.get("projectId") == project_id],
            key=lambda item: item.get("updatedAt", ""),
            reverse=True,
        )

    def get_chat(self, chat_id: str) -> dict[str, Any] | None:
        if self.engine is not None:
            try:
                with Session(self.engine) as session:
                    record = session.get(ChatRecord, chat_id)
                    return record.payload if record else None
            except SQLAlchemyError:
                pass
        return self.json_store.read()["chats"].get(chat_id)

    def save_memory(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": str(payload.get("id") or uuid.uuid4()),
            "projectId": project_id,
            "kind": str(payload.get("kind") or "note"),
            "key": str(payload.get("key") or ""),
            "value": payload.get("value") if isinstance(payload.get("value"), dict) else {"text": str(payload.get("value") or "")},
            "source": str(payload.get("source") or ""),
            "createdAt": payload.get("createdAt") or iso_now(),
            "updatedAt": iso_now(),
        }
        if self.engine is not None:
            try:
                with Session(self.engine) as session:
                    record = session.get(MemoryRecord, item["id"]) or MemoryRecord(id=item["id"], project_id=project_id, created_at=now())
                    record.project_id = project_id
                    record.kind = item["kind"]
                    record.key = item["key"]
                    record.value = item["value"]
                    record.source = item["source"]
                    record.updated_at = now()
                    session.add(record)
                    session.commit()
                return item
            except SQLAlchemyError:
                pass
        data = self.json_store.read()
        data["memories"][item["id"]] = item
        self.json_store.write(data)
        return item

    def list_memories(self, project_id: str) -> list[dict[str, Any]]:
        if self.engine is not None:
            try:
                with Session(self.engine) as session:
                    rows = session.scalars(select(MemoryRecord).where(MemoryRecord.project_id == project_id).order_by(MemoryRecord.updated_at.desc())).all()
                    return [
                        {
                            "id": row.id,
                            "projectId": row.project_id,
                            "kind": row.kind,
                            "key": row.key,
                            "value": row.value,
                            "source": row.source,
                            "createdAt": row.created_at.isoformat(),
                            "updatedAt": row.updated_at.isoformat(),
                        }
                        for row in rows
                    ]
            except SQLAlchemyError:
                pass
        return sorted(
            [item for item in self.json_store.read()["memories"].values() if item.get("projectId") == project_id],
            key=lambda item: item.get("updatedAt", ""),
            reverse=True,
        )

    def list_skills(self) -> list[dict[str, Any]]:
        skills_by_name = {skill["name"]: skill for skill in BUILTIN_SKILLS}
        if self.engine is not None:
            try:
                with Session(self.engine) as session:
                    skills_by_name.update({record.name: record.payload for record in session.scalars(select(SkillRecord)).all()})
                    return list(skills_by_name.values())
            except SQLAlchemyError:
                pass
        skills_by_name.update(self.json_store.read()["skills"])
        return list(skills_by_name.values())

    def save_skill(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload["name"])
        item = {
            "name": name,
            "trigger": payload.get("trigger") or f"/{name}",
            "description": payload.get("description") or "",
            "instructions": payload.get("instructions") or "",
            "tools": payload.get("tools") or [],
            "examples": payload.get("examples") or [],
            "builtin": bool(payload.get("builtin", False)),
            "createdAt": payload.get("createdAt") or iso_now(),
            "updatedAt": iso_now(),
        }
        if self.engine is not None:
            try:
                with Session(self.engine) as session:
                    record = session.get(SkillRecord, name) or SkillRecord(name=name, created_at=now())
                    record.trigger = item["trigger"]
                    record.description = item["description"]
                    record.payload = item
                    record.updated_at = now()
                    session.add(record)
                    session.commit()
                return item
            except SQLAlchemyError:
                pass
        data = self.json_store.read()
        data["skills"][name] = item
        self.json_store.write(data)
        return item

    def search(self, query: str, project_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
        needle = query.lower().strip()
        scoped_projects = [project for project in self.list_projects() if not project_id or project["id"] == project_id]
        if not needle:
            return {"projects": scoped_projects, "chats": [], "skills": self.list_skills(), "memories": []}
        projects = [item for item in scoped_projects if needle in item.get("name", "").lower() or needle in item.get("rootPath", "").lower()]
        skills = [item for item in self.list_skills() if needle in item.get("name", "").lower() or needle in item.get("description", "").lower()]
        chats: list[dict[str, Any]] = []
        memories: list[dict[str, Any]] = []
        for project in scoped_projects:
            chats.extend([chat for chat in self.list_chats(project["id"]) if needle in chat.get("title", "").lower() or needle in json.dumps(chat.get("messages", [])).lower()])
            memories.extend([memory for memory in self.list_memories(project["id"]) if needle in memory.get("key", "").lower() or needle in json.dumps(memory.get("value", {})).lower()])
        return {"projects": projects, "chats": chats, "skills": skills, "memories": memories}

    def save_upload(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = {"id": str(uuid.uuid4()), "createdAt": iso_now(), **payload}
        data = self.json_store.read()
        data["uploads"][item["id"]] = item
        self.json_store.write(data)
        return item
