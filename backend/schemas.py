from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    task: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    projectRoot: str | None = None
    projectId: str | None = None
    chatId: str | None = None
    planningMode: bool = False
    permissionMode: str = "safe"


class ModelSwitchRequest(BaseModel):
    model: str
    provider: str | None = None


class SettingsRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    ollamaUrl: str | None = None
    openaiApiKey: str | None = None


class SkillCreateRequest(BaseModel):
    name: str
    trigger: str | None = None
    description: str = ""
    instructions: str = ""
    tools: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class ProjectCreateRequest(BaseModel):
    name: str = "New Project"
    rootPath: str | None = None


class ChatCreateRequest(BaseModel):
    title: str = "New chat"
    messages: list[dict[str, Any]] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = ""
    projectId: str | None = None


class MemoryCreateRequest(BaseModel):
    kind: str = "note"
    key: str = ""
    value: dict[str, Any] = Field(default_factory=dict)
    source: str = ""
