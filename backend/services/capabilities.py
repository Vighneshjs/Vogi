from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: dict[str, Any]
    skill: str
    risk: str = "low"
    examples: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillSpec:
    name: str
    trigger: str
    description: str
    tools: list[str]
    workflow: list[str]


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec("get_system_info", "Inspect OS, project, storage, and runtime environment.", {"type": "object", "properties": {}}, "system"),
    ToolSpec("list_dir", "List files and folders in a directory.", {"type": "object", "properties": {"path": {"type": "string"}}}, "files"),
    ToolSpec("find_files", "Recursively search files by name or glob pattern.", {"type": "object", "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}}, "required": ["path"]}, "files"),
    ToolSpec("search_text", "Search literal text inside project files.", {"type": "object", "properties": {"path": {"type": "string"}, "query": {"type": "string"}}, "required": ["query"]}, "files"),
    ToolSpec("read_file", "Read a local file; use line ranges for large files.", {"type": "object", "properties": {"path": {"type": "string"}, "max_chars": {"type": "integer"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path"]}, "files"),
    ToolSpec("write_file", "Write a complete file with an undo snapshot.", {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}, "files", risk="medium"),
    ToolSpec("append_file", "Append content to a file with an undo snapshot.", {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}, "files", risk="medium"),
    ToolSpec("make_dir", "Create a directory with an undo snapshot.", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, "files"),
    ToolSpec("run_shell", "Run a safe PowerShell command in the selected project.", {"type": "object", "properties": {"command": {"type": "string"}, "cwd": {"type": "string"}, "timeout_ms": {"type": "integer"}}, "required": ["command"]}, "coding", risk="medium"),
    ToolSpec("install_package", "Install an application or Python package using winget or pip in Full Access mode and report verification/elevation requirements.", {"type": "object", "properties": {"manager": {"type": "string", "enum": ["winget", "pip"]}, "package": {"type": "string"}, "scope": {"type": "string", "enum": ["user", "machine"]}, "timeout_ms": {"type": "integer"}}, "required": ["package"]}, "system", risk="medium"),
    ToolSpec("database_query", "Connect to a SQLAlchemy-compatible database and execute a SQL query; Safe Mode is read-only.", {"type": "object", "properties": {"connectionUrl": {"type": "string"}, "sql": {"type": "string"}, "params": {"type": "object"}}, "required": ["sql"]}, "database", risk="medium"),
    ToolSpec("http_request", "Call an internal or external HTTP API; Safe Mode permits GET/HEAD and Full Access permits mutation requests.", {"type": "object", "properties": {"url": {"type": "string"}, "method": {"type": "string"}, "headers": {"type": "object"}, "json": {"type": "object"}, "body": {"type": "string"}, "timeout_ms": {"type": "integer"}}, "required": ["url"]}, "integrations", risk="medium"),
    ToolSpec("create_artifact", "Create formatted TXT, Markdown, HTML, DOCX, PDF, or slide HTML artifacts.", {"type": "object", "properties": {"path": {"type": "string"}, "title": {"type": "string"}, "format": {"type": "string", "enum": ["txt", "md", "html", "docx", "pdf", "slides-html"]}, "content": {"type": "string"}, "sections": {"type": "array"}}, "required": ["path", "content"]}, "documents"),
    ToolSpec("create_slides", "Create a lightweight presentation as HTML and an outline JSON file.", {"type": "object", "properties": {"path": {"type": "string"}, "title": {"type": "string"}, "slides": {"type": "array", "items": {"type": "object"}}}, "required": ["path", "slides"]}, "documents"),
    ToolSpec("web_search", "Search the public web for a natural-language query and return normalized candidate results.", {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}}, "research"),
    ToolSpec("browse_url", "Retrieve content from an HTTP/HTTPS URL using HTTP, rendered browser, PDF, image OCR, or an active authenticated browser session.", {"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}, "mode": {"type": "string", "enum": ["auto", "http", "rendered"]}, "session": {"type": "string", "enum": ["public", "authenticated"]}}, "required": ["url"]}, "research"),
    ToolSpec("browse_jobs", "Search public job pages for role/location keywords and return candidate listings.", {"type": "object", "properties": {"query": {"type": "string"}, "location": {"type": "string"}, "max_results": {"type": "integer"}}}, "jobs"),
    ToolSpec("prepare_job_application", "Create a job application packet using a resume file and job details. Does not submit externally.", {"type": "object", "properties": {"resume_path": {"type": "string"}, "job": {"type": "object"}, "output_dir": {"type": "string"}, "cover_letter": {"type": "string"}}}, "jobs", risk="medium"),
    ToolSpec("context_window_report", "Report current transcript/context size and suggest compression steps.", {"type": "object", "properties": {"history": {"type": "array"}, "task": {"type": "string"}}}, "system"),
    ToolSpec("create_command_tool", "Save a safe shell command as a reusable tool.", {"type": "object", "properties": {"name": {"type": "string"}, "command": {"type": "string"}, "description": {"type": "string"}}, "required": ["name", "command"]}, "tool_builder", risk="medium"),
    ToolSpec("list_command_tools", "List saved command tools.", {"type": "object", "properties": {}}, "tool_builder"),
    ToolSpec("run_command_tool", "Run a saved command tool.", {"type": "object", "properties": {"name": {"type": "string"}, "cwd": {"type": "string"}, "timeout_ms": {"type": "integer"}}, "required": ["name"]}, "tool_builder", risk="medium"),
    ToolSpec("create_schema", "Define a reusable JSON validation schema.", {"type": "object", "properties": {"name": {"type": "string"}, "schema": {"type": "object"}, "description": {"type": "string"}}, "required": ["name", "schema"]}, "tool_builder"),
    ToolSpec("list_schemas", "List registered schemas.", {"type": "object", "properties": {}}, "tool_builder"),
    ToolSpec("create_skill", "Save a custom skill with instructions and allowed tools.", {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "instructions": {"type": "string"}, "tools": {"type": "array"}}, "required": ["name", "instructions"]}, "skills"),
    ToolSpec("list_skills", "List built-in and user-created skills.", {"type": "object", "properties": {}}, "skills"),
    ToolSpec("remember_project", "Save a durable project note.", {"type": "object", "properties": {"project_id": {"type": "string"}, "key": {"type": "string"}, "value": {"type": "object"}}, "required": ["project_id", "key", "value"]}, "memory"),
    ToolSpec("recall_project", "Retrieve project memories.", {"type": "object", "properties": {"project_id": {"type": "string"}}, "required": ["project_id"]}, "memory"),
    ToolSpec("undo_last_change", "Undo the last file change made by Vogi.", {"type": "object", "properties": {}}, "files", risk="medium"),
    ToolSpec("ask_user", "Ask the user a clarifying question when a task is ambiguous, has multiple options, or requires user preferences before proceeding.", {"type": "object", "properties": {"question": {"type": "string", "description": "The clarifying question to ask."}}, "required": ["question"]}, "skills"),
]


SKILL_SPECS: list[SkillSpec] = [
    SkillSpec("coding_agent", "/code", "Read, edit, run, test, debug, and optimize local codebases.", ["find_files", "search_text", "read_file", "write_file", "run_shell", "install_package", "database_query", "http_request", "context_window_report"], ["Inspect repo structure", "Find relevant files", "Read before editing", "Patch focused changes", "Run focused tests", "Report exact files and verification"]),
    SkillSpec("research_agent", "/web", "Search, browse, and synthesize current web information from pages and documents.", ["web_search", "browse_url", "browse_jobs"], ["Search or open authoritative pages", "Retrieve HTML, rendered pages, PDFs, or images as needed", "Extract verified facts", "Cite URLs in final answer"]),
    SkillSpec("job_application_agent", "/jobs", "Find jobs and prepare application packets from a user resume.", ["browse_jobs", "read_file", "prepare_job_application", "create_artifact"], ["Search jobs", "Select relevant listings", "Read specified resume", "Create tailored application packet", "Ask before external submission"]),
    SkillSpec("document_agent", "/docs", "Create formatted documents, PDFs, reports, and slide outlines.", ["create_artifact", "create_slides", "read_file"], ["Gather content", "Choose artifact format", "Create structured output", "Verify file exists"]),
    SkillSpec("memory_agent", "/memory", "Store and recall project-specific facts.", ["remember_project", "recall_project"], ["Recall relevant memory", "Save stable facts only", "Use memories in future work"]),
    SkillSpec("tool_builder", "/tool", "Create reusable tools and schemas.", ["create_command_tool", "list_command_tools", "run_command_tool", "create_schema", "list_schemas"], ["Validate safety", "Create reusable command/schema", "Test it when possible"]),
    SkillSpec("operations_agent", "/ops", "Install software, query databases, and call internal application APIs under the active permission mode.", ["get_system_info", "run_shell", "install_package", "database_query", "http_request"], ["Check environment", "Perform the requested operation", "Verify actual outcome", "Report permission or service blockers honestly"]),
]


class CapabilityRegistry:
    def __init__(self) -> None:
        self.tools = {item.name: item for item in TOOL_SPECS}
        self.skills = {item.name: item for item in SKILL_SPECS}

    def tool_prompt(self) -> str:
        payload = {
            name: {
                "description": spec.description,
                "params": spec.params,
                "skill": spec.skill,
                "risk": spec.risk,
            }
            for name, spec in self.tools.items()
        }
        return str(payload)

    def skill_prompt(self) -> str:
        return str({
            name: {
                "trigger": skill.trigger,
                "description": skill.description,
                "tools": skill.tools,
                "workflow": skill.workflow,
            }
            for name, skill in self.skills.items()
        })

    def public_skills(self) -> list[dict[str, Any]]:
        return [
            {
                "name": skill.name,
                "trigger": skill.trigger,
                "description": skill.description,
                "tools": skill.tools,
                "workflow": skill.workflow,
                "builtin": True,
            }
            for skill in self.skills.values()
        ]

    def tools_for_prompt(self, task: str) -> list[str]:
        text = task.lower()
        if text.strip().startswith(("/upgrade", "/code")):
            return sorted({"get_system_info", "find_files", "search_text", "read_file", "write_file", "append_file", "make_dir", "run_shell", "install_package", "database_query", "http_request", "context_window_report", "ask_user"})
        selected: set[str] = {"context_window_report", "list_skills", "ask_user"}
        if any(word in text for word in ["code", "repo", "bug", "fix", "run", "test", "edit", "remove", "change", "ui", "screen", "frontend", "backend", "upgrade", "file", "folder"]):
            selected.update(self.skills["coding_agent"].tools)
        if any(word in text for word in ["job", "resume", "apply", "frontend", "developer", "career"]):
            selected.update(self.skills["job_application_agent"].tools)
        if any(word in text for word in ["pdf", "doc", "document", "slides", "ppt", "report", "format", "graph", "chart", "plot", "visualize"]):
            selected.update(self.skills["document_agent"].tools)
        if any(word in text for word in ["browse", "web", "search", "url", "latest", "open", "news", "price", "compare", "find", "look up"]):
            selected.update(self.skills["research_agent"].tools)
        if any(word in text for word in ["remember", "memory", "recall"]):
            selected.update(self.skills["memory_agent"].tools)
        if any(word in text for word in ["tool", "schema", "command"]):
            selected.update(self.skills["tool_builder"].tools)
        if any(word in text for word in ["install", "package", "redis", "dependency", "winget", "pip"]):
            selected.add("install_package")
        if any(word in text for word in ["database", "db", "sql", "postgres", "mysql", "sqlite", "query"]):
            selected.add("database_query")
        if any(word in text for word in ["api", "endpoint", "internal application", "internal app", "service"]):
            selected.add("http_request")
        selected.update(["get_system_info", "read_file", "write_file", "run_shell"])
        return sorted(selected)


class HierarchicalPlanner:
    def __init__(self, registry: CapabilityRegistry | None = None) -> None:
        self.registry = registry or CapabilityRegistry()

    def intent(self, task: str) -> str:
        text = task.lower()
        if text.strip().startswith(("/upgrade", "/code")):
            return "coding.execute"
        if any(word in text for word in ["install", "package", "redis", "dependency", "winget", "pip install"]):
            return "system.install"
        if any(word in text for word in ["database", "sql", "postgres", "mysql", "sqlite"]) and any(word in text for word in ["query", "connect", "select", "insert", "update", "delete"]):
            return "data.query"
        if any(phrase in text for phrase in ["internal application", "internal app", "internal api", "call api", "api endpoint"]):
            return "integration.request"
        if any(word in text for word in ["job", "resume", "apply", "cover letter", "application"]):
            return "consumer.jobs"
        if any(word in text for word in ["graph", "chart", "plot", "visualize"]) and any(word in text for word in ["price", "compare", "latest", "current", "search", "web", "deal", "buying"]):
            return "consumer.artifact_from_research"
        if "documentation page" in text or "docs page" in text:
            return "consumer.research_compare"
        if any(word in text for word in ["price", "prices", "deal", "deals", "buy", "buying", "compare", "cheapest", "latest", "current", "news", "deadline"]):
            return "consumer.research_compare"
        if any(word in text for word in ["inspect", "where is", "where are", "find where", "which file", "codebase", "project"]) and any(word in text for word in ["file", "sidebar", "skills", "text", "defined", "appears", "located"]):
            return "project.inspect"
        if any(word in text for word in ["recall", "remember", "memory"]):
            return "memory.only"
        if any(word in text for word in ["job", "resume", "apply"]):
            return "jobs.apply_or_prepare"
        if any(word in text for word in ["pdf", "doc", "document", "slides", "ppt", "report", "graph", "chart", "plot", "visualize"]):
            return "documents.create_or_format"
        if any(word in text for word in ["code", "repo", "bug", "fix", "test", "run", "edit", "remove", "change", "ui", "screen", "frontend", "backend", "upgrade"]):
            return "coding.execute"
        if any(word in text for word in ["browse", "search", "web", "url", "latest", "news", "price", "compare", "find", "look up"]):
            return "research.browse"
        if any(word in text for word in ["remember", "memory", "recall"]):
            return "memory.manage"
        return "general.assist"

    def skill_chain(self, task: str) -> list[str]:
        intent = self.intent(task)
        if intent == "consumer.jobs":
            return ["job_application_agent", "research_agent", "document_agent"]
        if intent == "consumer.artifact_from_research":
            return ["research_agent", "document_agent"]
        if intent == "consumer.research_compare":
            return ["research_agent"]
        if intent == "project.inspect":
            return ["coding_agent"]
        if intent == "memory.only":
            return ["memory_agent"]
        if intent == "jobs.apply_or_prepare":
            return ["job_application_agent", "research_agent", "document_agent"]
        if intent == "documents.create_or_format":
            if any(word in task.lower() for word in ["latest", "price", "compare", "search", "web", "find", "look up"]):
                return ["research_agent", "document_agent"]
            return ["document_agent"]
        if intent == "coding.execute":
            return ["coding_agent"]
        if intent in {"system.install", "data.query", "integration.request"}:
            return ["operations_agent"]
        if intent == "research.browse":
            return ["research_agent"]
        if intent == "memory.manage":
            return ["memory_agent"]
        return ["coding_agent", "document_agent", "research_agent"]

    def plan(self, task: str) -> dict[str, Any]:
        skills = self.skill_chain(task)
        workflows: list[str] = []
        tools: set[str] = set()
        for name in skills:
            skill = self.registry.skills[name]
            workflows.extend(skill.workflow)
            tools.update(skill.tools)
        tools.update(self.registry.tools_for_prompt(task))
        return {
            "intent": self.intent(task),
            "selectedSkills": skills,
            "allowedTools": sorted(tools),
            "workflow": list(dict.fromkeys(workflows)),
            "rules": [
                "Use tools whenever local files, current web facts, code execution, or artifact creation are needed.",
                "Consumer web, job, project-inspection, and artifact tasks must use the required tool workflow before final.",
                "Read before editing. Test after editing when a runnable command exists.",
                "Keep context compact: summarize large outputs and use line ranges for large files.",
                "Do not submit job applications, send emails, or perform irreversible external actions without user confirmation.",
            ],
        }
