from __future__ import annotations

from ..config import Settings
from ..db import Storage


class BootstrapService:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.storage = storage

    def payload(self) -> dict:
        projects = self.storage.list_projects()
        active_project = projects[0] if projects else self.storage.ensure_default_project()
        return {
            "ok": True,
            "app": {
                "name": "Vogi",
                "tagline": "Agentic AI Workspace",
                "welcome": "Ready. I am Vogi, running on the standalone Python backend. I can plan, inspect files, edit code, run safe commands, create tools and skills, browse URLs, inspect images, and connect to local or API-key models.",
            },
            "projectRoot": str(self.settings.root_dir),
            "activeProjectId": active_project["id"],
            "storage": {"mode": self.storage.mode, "databaseUrlConfigured": bool(self.settings.database_url)},
            "runtime": {
                "provider": self.settings.model_provider,
                "model": self.settings.agent_model,
                "inspectionModel": self.settings.inspection_model,
                "ollamaUrl": self.settings.ollama_url,
            },
            "skills": self.storage.list_skills(),
            "projects": projects,
            "chats": self.storage.list_chats(active_project["id"]),
            "memories": self.storage.list_memories(active_project["id"]),
        }
