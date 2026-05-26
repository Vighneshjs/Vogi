from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import time
import httpx
from typing import Any, AsyncIterator

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import Storage
from .exceptions import ModelProviderError, VogiError
from .schemas import AgentRequest, ChatCreateRequest, MemoryCreateRequest, ModelSwitchRequest, ProjectCreateRequest, SearchRequest, SettingsRequest, SkillCreateRequest
from .services.agent import AgentService
from .services.bootstrap import BootstrapService
from .services.model_router import ModelRouter
from .services.tools import ToolService
from .services.utils import iso_now, slugify, read_json


settings = get_settings()
storage = Storage(settings)
models = ModelRouter(settings)
tools = ToolService(settings, storage)
agent_service = AgentService(settings, models, tools)
bootstrap_service = BootstrapService(settings, storage)

app = FastAPI(title="Vogi Standalone Agent", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

if settings.reports_dir.exists():
    app.mount("/reports", StaticFiles(directory=str(settings.reports_dir)), name="reports")
app.mount("/assets", StaticFiles(directory=str(settings.public_dir)), name="assets")


@app.exception_handler(VogiError)
async def handle_vogi_error(_request: Request, exc: VogiError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(settings.public_dir / "index.html")


@app.get("/agent")
@app.get("/platform")
async def platform() -> FileResponse:
    return FileResponse(settings.public_dir / "index.html")


@app.get("/api/bootstrap")
async def bootstrap() -> dict[str, Any]:
    return bootstrap_service.payload()


@app.get("/api/projects")
async def list_projects() -> dict[str, Any]:
    return {"projects": storage.list_projects(), "storage": storage.mode}


def resolve_project_root(project_id: str | None, project_root: str | None = None):
    if project_id:
        project = storage.get_project(project_id)
        if project:
            return tools.normalize_path(project.get("rootPath") or str(settings.root_dir), settings.root_dir)
    return tools.normalize_path(project_root or str(settings.root_dir), settings.root_dir)


@app.post("/api/projects")
async def create_project(request: ProjectCreateRequest) -> dict[str, Any]:
    project = storage.create_project(request.name, request.rootPath)
    chat = storage.ensure_default_chat(project["id"])
    return {"project": project, "chat": chat, "chats": storage.list_chats(project["id"]), "memories": storage.list_memories(project["id"])}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"project": project, "chats": storage.list_chats(project_id), "memories": storage.list_memories(project_id)}


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, Any]:
    if not storage.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    storage.delete_project(project_id)
    return {"ok": True, "projectId": project_id}


@app.get("/api/projects/{project_id}/chats")
async def list_project_chats(project_id: str) -> dict[str, Any]:
    if not storage.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"chats": storage.list_chats(project_id)}


@app.post("/api/projects/{project_id}/chats")
async def create_project_chat(project_id: str, request: ChatCreateRequest) -> dict[str, Any]:
    if not storage.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"chat": storage.save_chat(project_id, request.model_dump())}


@app.get("/api/chats/{chat_id}")
async def get_chat(chat_id: str) -> dict[str, Any]:
    chat = storage.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return {"chat": chat}


@app.post("/api/projects/{project_id}/memories")
async def create_project_memory(project_id: str, request: MemoryCreateRequest) -> dict[str, Any]:
    if not storage.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"memory": storage.save_memory(project_id, request.model_dump())}


@app.get("/api/projects/{project_id}/memories")
async def list_project_memories(project_id: str) -> dict[str, Any]:
    if not storage.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"memories": storage.list_memories(project_id)}


@app.post("/api/search")
async def search(request: SearchRequest) -> dict[str, Any]:
    return storage.search(request.query, request.projectId)


@app.post("/api/files/upload")
async def upload_file(file: UploadFile = File(...), projectId: str | None = None) -> dict[str, Any]:
    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File is larger than 8 MB.")
    text_preview = ""
    try:
        text_preview = content[:20000].decode("utf-8")
    except UnicodeDecodeError:
        text_preview = base64.b64encode(content[:4096]).decode("ascii")
    upload = storage.save_upload({
        "projectId": projectId,
        "filename": file.filename,
        "contentType": file.content_type,
        "size": len(content),
        "preview": text_preview,
    })
    return {"upload": upload}


@app.get("/api/health")
async def health() -> JSONResponse:
    try:
        installed = bool(settings.openai_api_key) if settings.model_provider == "openai" else settings.agent_model in await models.list_models()
        return JSONResponse({
            "ok": True,
            "provider": settings.model_provider,
            "model": settings.agent_model,
            "agentModel": settings.agent_model,
            "installed": installed,
            "ollamaUrl": settings.ollama_url,
            "storage": storage.mode,
        })
    except ModelProviderError as exc:
        return JSONResponse({"ok": False, "provider": settings.model_provider, "model": settings.agent_model, "error": str(exc), "storage": storage.mode}, status_code=503)


@app.get("/api/models")
async def list_models() -> JSONResponse:
    try:
        available = await models.list_models()
        return JSONResponse({"provider": settings.model_provider, "model": settings.agent_model, "models": available})
    except ModelProviderError as exc:
        return JSONResponse({"provider": settings.model_provider, "model": settings.agent_model, "models": [], "error": str(exc)}, status_code=503)


async def check_and_start_ollama(model: str):
    ollama_url = settings.ollama_url
    is_running = False
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            res = await client.get(f"{ollama_url}/api/tags")
            if res.status_code == 200:
                is_running = True
    except Exception:
        pass
        
    if not is_running:
        try:
            creationflags = 0x08000000 if os.name == "nt" else 0
            subprocess.Popen(["ollama", "serve"], creationflags=creationflags)
            for _ in range(30):
                await asyncio.sleep(1)
                try:
                    async with httpx.AsyncClient(timeout=1) as client:
                        res = await client.get(f"{ollama_url}/api/tags")
                        if res.status_code == 200:
                            is_running = True
                            break
                except Exception:
                    pass
        except Exception as e:
            print(f"Failed to start Ollama: {e}")
            
    if is_running:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.get(f"{ollama_url}/api/tags")
                models_list = [item.get("name") or item.get("model") for item in res.json().get("models", []) if item.get("name") or item.get("model")]
        except Exception:
            models_list = []
            
        if model not in models_list and f"{model}:latest" not in models_list:
            try:
                creationflags = 0x08000000 if os.name == "nt" else 0
                process = await asyncio.create_subprocess_exec(
                    "ollama", "pull", model,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags
                )
                await process.wait()
            except Exception as e:
                print(f"Failed to pull model {model}: {e}")


@app.post("/api/ollama/start")
async def start_ollama_model(request: ModelSwitchRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    model_name = request.model.strip() or "gemma3:1b"
    background_tasks.add_task(check_and_start_ollama, model_name)
    return {"ok": True, "message": f"Start task for {model_name} triggered in the background."}


@app.post("/api/model")
async def switch_model(request: ModelSwitchRequest) -> dict[str, Any]:
    model_name = request.model.strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="Model name is required.")
        
    provider = request.provider
    if "gemma" in model_name.lower():
        provider = "ollama"
    elif any(m in model_name.lower() for m in ["gpt", "o1", "o3", "o4"]):
        provider = "openai"
        
    if provider:
        settings.model_provider = provider.lower()
    settings.agent_model = model_name
    return {"provider": settings.model_provider, "model": settings.agent_model}


@app.post("/api/settings")
async def update_settings(request: SettingsRequest) -> dict[str, Any]:
    if request.provider:
        settings.model_provider = request.provider.lower()
    if request.model:
        settings.agent_model = request.model.strip()
    if request.ollamaUrl:
        settings.ollama_url = request.ollamaUrl.rstrip("/")
    if request.openaiApiKey:
        settings.openai_api_key = request.openaiApiKey
        os.environ["OPENAI_API_KEY"] = request.openaiApiKey
    return {"ok": True, "provider": settings.model_provider, "model": settings.agent_model, "ollamaUrl": settings.ollama_url}


@app.get("/api/browser-session")
async def browser_session_status() -> dict[str, Any]:
    return await tools.browser_sessions.status()


@app.post("/api/browser-session/start")
async def start_browser_session() -> dict[str, Any]:
    return await tools.browser_sessions.start_authenticated()


@app.post("/api/browser-session/close")
async def close_browser_session() -> dict[str, Any]:
    return await tools.browser_sessions.close_authenticated()


@app.get("/api/settings")
async def get_runtime_settings() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": settings.model_provider,
        "model": settings.agent_model,
        "agentModel": settings.agent_model,
        "ollamaUrl": settings.ollama_url,
        "openaiConfigured": bool(settings.openai_api_key),
        "storage": storage.mode,
    }


@app.get("/api/runtime/diagnose")
async def diagnose() -> JSONResponse:
    started = time.time()
    try:
        data = await models.chat([{"role": "user", "content": "Say ready."}], num_predict=4, temperature=0, timeout=25)
        return JSONResponse({"ok": True, "provider": settings.model_provider, "model": settings.agent_model, "elapsedMs": round((time.time() - started) * 1000), "response": data.get("message", {}).get("content", "")})
    except Exception as exc:
        return JSONResponse({"ok": False, "provider": settings.model_provider, "model": settings.agent_model, "elapsedMs": round((time.time() - started) * 1000), "error": str(exc)}, status_code=503)


@app.post("/api/agent")
async def agent_json(request: AgentRequest) -> dict[str, Any]:
    if not request.task.strip():
        raise HTTPException(status_code=400, detail="Agent task is required.")
    project_root = resolve_project_root(request.projectId, request.projectRoot)
    result = await agent_service.run(request.task.strip(), request.history, str(project_root), project_id=request.projectId, planning_mode=request.planningMode, attachments=request.attachments, permission_mode=request.permissionMode)
    if request.chatId:
        user_message = {"role": "user", "content": request.task}
        if request.attachments:
            user_message["attachments"] = request.attachments
        storage.save_chat(request.projectId or storage.ensure_default_project()["id"], {
            "id": request.chatId,
            "title": request.task.strip()[:60] or "Chat",
            "messages": [*request.history, user_message, {"role": "assistant", "content": result.get("final", ""), "files": result.get("files", []), "changes": result.get("changes", [])}],
            "plan": result.get("plan", []),
            "trace": result.get("transcript", []),
        })
    effective_root = result.get("projectRoot") or str(project_root)
    return {"provider": settings.model_provider, "model": settings.agent_model, "agentRoot": str(settings.root_dir), "projectRoot": effective_root, "maxSteps": settings.max_agent_steps, **result}


@app.post("/api/agent/stream")
async def agent_stream(request: AgentRequest) -> StreamingResponse:
    async def events() -> AsyncIterator[bytes]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put({"time": iso_now(), **event})

        async def worker() -> None:
            try:
                if not request.task.strip():
                    await emit({"type": "error", "error": "Agent task is required."})
                    return
                await emit({"type": "status", "status": "Upgrade mode active. Vogi will inspect and improve itself through tools." if request.task.strip().lower().startswith("/upgrade") else "Request received."})
                project_root = resolve_project_root(request.projectId, request.projectRoot)
                result = await agent_service.run(request.task.strip(), request.history, str(project_root), emit, project_id=request.projectId, planning_mode=request.planningMode, attachments=request.attachments, permission_mode=request.permissionMode)
                if request.chatId:
                    user_message = {"role": "user", "content": request.task}
                    if request.attachments:
                        user_message["attachments"] = request.attachments
                    storage.save_chat(request.projectId or storage.ensure_default_project()["id"], {
                        "id": request.chatId,
                        "title": request.task.strip()[:60] or "Chat",
                        "messages": [*request.history, user_message, {"role": "assistant", "content": result.get("final", ""), "files": result.get("files", []), "changes": result.get("changes", [])}],
                        "plan": result.get("plan", []),
                        "trace": result.get("transcript", []),
                    })
                effective_root = result.get("projectRoot") or str(project_root)
                await emit({"type": "done", "provider": settings.model_provider, "model": settings.agent_model, "agentRoot": str(settings.root_dir), "projectRoot": effective_root, "maxSteps": settings.max_agent_steps, **result})
            except Exception as exc:
                await emit({"type": "error", "error": str(exc)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield (json.dumps(item) + "\n").encode("utf-8")
        finally:
            task.cancel()

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.post("/api/agent/undo")
async def undo() -> dict[str, Any]:
    return tools.undo_last_change()


@app.post("/api/select-folder")
async def select_folder(request: Request) -> dict[str, Any]:
    body = await request.json()
    mode = "create" if body.get("mode") == "create" else "open"
    description = "Create or select a folder for the new Vogi project" if mode == "create" else "Open an existing project folder in Vogi"
    start_path = str(tools.normalize_path(body.get("startPath") or str(settings.root_dir), settings.root_dir))
    ps_script = "; ".join([
        "Add-Type -AssemblyName System.Windows.Forms",
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog",
        f"$dialog.Description = {json.dumps(description)}",
        f"$dialog.SelectedPath = {json.dumps(start_path)}",
        "$dialog.ShowNewFolderButton = $true",
        "$owner = New-Object System.Windows.Forms.Form",
        "$owner.TopMost = $true",
        "$owner.ShowInTaskbar = $false",
        "$owner.Opacity = 0",
        "$owner.StartPosition = 'CenterScreen'",
        "$owner.Show()",
        "$owner.Activate()",
        "try { if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { $dialog.SelectedPath } } finally { $owner.Close(); $owner.Dispose(); $dialog.Dispose() }",
    ])
    completed = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps_script], cwd=str(settings.root_dir), capture_output=True, text=True, timeout=120)
    selected = completed.stdout.strip()
    return {"cancelled": not bool(selected), "path": selected or None, "mode": mode}


@app.get("/api/skills")
async def list_skills() -> dict[str, Any]:
    file_skills = [read_json(path) for path in settings.tools_dir.glob("*.skill.json")] if settings.tools_dir.exists() else []
    all_skills = storage.list_skills() + file_skills
    return {"skills": all_skills, "storage": storage.mode}


@app.get("/api/tools")
async def list_tools() -> dict[str, Any]:
    return {
        "tools": {
            name: {
                "description": spec.description,
                "params": spec.params,
                "skill": spec.skill,
                "risk": spec.risk,
                "examples": spec.examples,
            }
            for name, spec in tools.capabilities.tools.items()
        },
        "skills": tools.capabilities.public_skills(),
    }


@app.post("/api/plan")
async def plan_task(request: AgentRequest) -> dict[str, Any]:
    return {
        "task": request.task,
        "plan": agent_service.planner.plan(request.task),
    }


@app.post("/api/tools/run")
async def run_tool(request: Request) -> dict[str, Any]:
    body = await request.json()
    action = body.get("action") or {"tool": body.get("tool"), "args": body.get("args") or {}}
    project_root = tools.normalize_path(body.get("projectRoot") or str(settings.root_dir), settings.root_dir)
    result = await tools.execute(action, project_root, body.get("permissionMode") or "safe")
    return {"action": action, "result": result}


@app.post("/api/skills")
async def create_skill(request: SkillCreateRequest) -> dict[str, Any]:
    payload = {
        "name": slugify(request.name),
        "trigger": request.trigger or f"/{slugify(request.name)}",
        "description": request.description,
        "instructions": request.instructions,
        "tools": request.tools,
        "examples": request.examples,
    }
    return {"skill": storage.save_skill(payload), "storage": storage.mode}


@app.post("/api/skills/{name}/run")
async def run_skill(name: str, request: AgentRequest) -> dict[str, Any]:
    file_skills = [read_json(path) for path in settings.tools_dir.glob("*.skill.json")] if settings.tools_dir.exists() else []
    all_skills = storage.list_skills() + file_skills
    skill = next((item for item in all_skills if item.get("name") == name or item.get("trigger") == f"/{name}"), None)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found.")
    task = request.task.strip() if request.task.strip() in {"/is", "/ is"} else f"{skill.get('trigger', '/' + name)} {request.task}".strip()
    project_root = resolve_project_root(request.projectId, request.projectRoot)
    result = await agent_service.run(task, request.history, str(project_root), project_id=request.projectId, planning_mode=request.planningMode, attachments=request.attachments, permission_mode=request.permissionMode)
    return {"skill": skill, **result}
