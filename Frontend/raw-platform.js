const q = (name) => document.querySelector(`[data-vogi="${name}"]`);
const qa = (name) => Array.from(document.querySelectorAll(`[data-vogi="${name}"]`));

const dom = {
  logo: q("logo"),
  agentLogo: q("agent-logo"),
  runningVideo: q("running-video"),
  newProject: q("new-project"),
  openProject: q("open-project"),
  newChat: q("new-chat"),
  searchButton: q("search-button"),
  searchInput: q("search-input"),
  projectList: q("project-list"),
  sidebarSkills: q("sidebar-skills"),
  chatScroll: q("chat-scroll"),
  skillsDropdown: q("skills-dropdown"),
  skillsButton: q("skills-button"),
  attachButton: q("attach-button"),
  fileInput: q("file-input"),
  composer: q("composer"),
  planningToggle: q("planning-toggle"),
  send: q("send"),
  stop: q("stop"),
  runBadge: q("run-badge"),
  executionPlan: q("execution-plan"),
  processOutput: q("process-output"),
  settingsModal: q("settings-modal")
};

const state = {
  bootstrap: null,
  projects: [],
  chats: [],
  memories: [],
  skills: [],
  activeProjectId: null,
  activeChatId: null,
  planningMode: true,
  sending: false,
  controller: null,
  collapsedProjects: new Set()
};

function text(value) {
  return String(value ?? "");
}

function shortTime(value) {
  if (!value) return "now";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "now";
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 1440) return `${Math.round(minutes / 60)}h`;
  return `${Math.round(minutes / 1440)}d`;
}

function icon(name, classes = "text-[16px]") {
  const span = document.createElement("span");
  span.className = `material-symbols-outlined ${classes}`;
  span.textContent = name;
  return span;
}

function activeProject() {
  return state.projects.find((project) => project.id === state.activeProjectId) ?? state.projects[0];
}

function activeChat() {
  return state.chats.find((chat) => chat.id === state.activeChatId) ?? state.chats[0];
}

function setBusy(isBusy) {
  dom.send.disabled = isBusy;
  dom.send.classList.toggle("hidden", isBusy);
  dom.stop.classList.toggle("hidden", !isBusy);
  dom.composer.disabled = isBusy;
  dom.runBadge.textContent = isBusy ? "Running" : "Idle";
  dom.runningVideo.classList.toggle("hidden", !isBusy);
  dom.agentLogo.classList.toggle("hidden", isBusy);
  if (isBusy && typeof dom.runningVideo.play === "function") dom.runningVideo.play().catch(() => {});
}

function clearDemoMessages() {
  for (const phrase of ["Let's build a new endpoint", "I'll create a new Express route", "recent activity logs"]) {
    for (const node of Array.from(dom.chatScroll.querySelectorAll("p"))) {
      if (node.textContent.includes(phrase)) {
        (node.closest(".group") ?? node.closest("div"))?.remove();
      }
    }
  }
}

function messageNode(message) {
  const role = message.role === "user" ? "user" : "assistant";
  const wrap = document.createElement("div");
  wrap.className = role === "user" ? "flex gap-4 self-end max-w-[85%] group" : "flex gap-4 max-w-[90%] group";
  if (role === "user") {
    wrap.innerHTML = `
      <div class="flex flex-col items-end gap-1">
        <div class="bg-surface-container text-on-surface px-5 py-3 rounded-2xl rounded-tr-sm border border-outline-variant/50 shadow-sm relative">
          <p class="font-body-md text-body-md leading-relaxed whitespace-pre-wrap"></p>
        </div>
      </div>
      <div class="w-8 h-8 rounded-full bg-surface-variant flex items-center justify-center flex-shrink-0 border border-outline-variant">
        <span class="material-symbols-outlined text-[18px] text-on-surface">person</span>
      </div>`;
  } else {
    wrap.innerHTML = `
      <div class="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 border border-primary/30 overflow-hidden">
        <img alt="Agent" class="w-full h-full object-cover" src="/assets/assets/vogi-logo.png"/>
      </div>
      <div class="flex flex-col items-start gap-2 w-full">
        <div class="flex items-center gap-2 mb-1">
          <span class="font-title-md text-title-md text-on-surface text-[14px]">Vogi</span>
          <span class="font-code-label text-code-label text-on-surface-variant text-[12px]">local</span>
        </div>
        <div class="text-on-surface font-body-md text-body-md leading-relaxed space-y-4 w-full message-content">
          <p class="whitespace-pre-wrap"></p>
        </div>
      </div>`;
  }
  wrap.querySelector("p").textContent = text(message.content);
  if (role === "assistant" && message.files && message.files.length > 0) {
      const filesDiv = document.createElement("div");
      filesDiv.className = "mt-4 bg-surface-container-low border border-outline-variant rounded-lg p-3 w-full max-w-md";
      filesDiv.innerHTML = `
          <div class="flex items-center justify-between mb-2">
              <span class="text-[12px] font-code-label uppercase text-on-surface-variant font-semibold">Files Modified (${message.files.length})</span>
              <button class="undo-change-btn text-[12px] flex items-center gap-1 text-primary hover:text-primary-fixed transition-colors bg-primary/10 px-2 py-1 rounded">
                  <span class="material-symbols-outlined text-[14px]">undo</span> Undo
              </button>
          </div>
          <ul class="flex flex-col gap-1.5">
              ${message.files.map(f => `<li class="text-[13px] font-code-label text-on-surface truncate" title="${f}"><span class="text-tertiary">~</span> ${f.split(/[\\\\/]/).pop()}</li>`).join("")}
          </ul>
      `;
      wrap.querySelector(".message-content").appendChild(filesDiv);
      const undoBtn = filesDiv.querySelector(".undo-change-btn");
      undoBtn.addEventListener("click", async () => {
          if (undoBtn.disabled) return;
          undoBtn.disabled = true;
          undoBtn.innerHTML = `<span class="material-symbols-outlined text-[14px] animate-spin">sync</span> Undoing...`;
          try {
              const res = await fetch("/api/agent/undo", { method: "POST" });
              const data = await res.json();
              if (data.undone) {
                  undoBtn.innerHTML = `<span class="material-symbols-outlined text-[14px]">check</span> Undone`;
                  undoBtn.classList.replace("text-primary", "text-[#4ade80]");
                  undoBtn.classList.replace("bg-primary/10", "bg-[#4ade80]/10");
                  undoBtn.classList.remove("hover:text-primary-fixed");
              } else {
                  undoBtn.innerHTML = `<span class="material-symbols-outlined text-[14px]">error</span> ${data.message || "Failed"}`;
                  undoBtn.classList.replace("text-primary", "text-error");
                  undoBtn.classList.replace("bg-primary/10", "bg-error/10");
              }
          } catch (e) {
              undoBtn.innerHTML = `<span class="material-symbols-outlined text-[14px]">error</span> Error`;
              undoBtn.classList.replace("text-primary", "text-error");
              undoBtn.classList.replace("bg-primary/10", "bg-error/10");
          }
      });
  }
  return wrap;
}

function renderMessages() {
  clearDemoMessages();
  dom.chatScroll.querySelector("[data-live-chat]")?.remove();
  const live = document.createElement("div");
  live.dataset.liveChat = "true";
  live.className = "flex flex-col gap-8";
  const chat = activeChat();
  for (const message of chat?.messages ?? []) live.append(messageNode(message));
  
  if (state.sending) {
    const thinkingWrap = document.createElement("div");
    thinkingWrap.className = "flex gap-4 max-w-[90%] group";
    thinkingWrap.innerHTML = `
      <div class="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 border border-primary/30 overflow-hidden">
        <img alt="Agent" class="w-full h-full object-cover" src="/assets/assets/vogi-running.gif"/>
      </div>
      <div class="flex flex-col items-start gap-2 w-full">
        <div class="flex items-center gap-2 mb-1 cursor-pointer select-none group/toggle" id="thinking-dropdown-toggle">
          <span class="font-title-md text-title-md text-on-surface text-[14px]">Vogi</span>
          <span class="font-code-label text-code-label text-on-surface-variant text-[12px] animate-pulse">thinking...</span>
          <span class="material-symbols-outlined text-[16px] text-on-surface-variant group-hover/toggle:text-on-surface transition-colors transition-transform duration-200" id="thinking-dropdown-icon">expand_more</span>
        </div>
        <div class="hidden flex-col gap-1 w-full max-w-lg mt-1 mb-2 p-3 bg-surface-container-low border border-outline-variant/60 shadow-sm rounded-lg max-h-[300px] overflow-y-auto" id="thinking-steps-container">
        </div>
        <div class="text-on-surface font-body-md text-body-md leading-relaxed space-y-4 w-full">
          <div class="flex items-center gap-1.5 mt-1.5 opacity-60">
            <span class="w-2 h-2 bg-on-surface rounded-full animate-bounce" style="animation-delay: 0ms"></span>
            <span class="w-2 h-2 bg-on-surface rounded-full animate-bounce" style="animation-delay: 150ms"></span>
            <span class="w-2 h-2 bg-on-surface rounded-full animate-bounce" style="animation-delay: 300ms"></span>
          </div>
        </div>
      </div>`;
      
    const toggle = thinkingWrap.querySelector("#thinking-dropdown-toggle");
    const container = thinkingWrap.querySelector("#thinking-steps-container");
    const icon = thinkingWrap.querySelector("#thinking-dropdown-icon");
    toggle.addEventListener("click", () => {
      container.classList.toggle("hidden");
      icon.style.transform = container.classList.contains("hidden") ? "" : "rotate(180deg)";
    });
    
    live.append(thinkingWrap);
  }

  dom.chatScroll.append(live);
  dom.chatScroll.scrollTop = dom.chatScroll.scrollHeight;
}

function renderProjects() {
  dom.projectList.innerHTML = "";
  for (const project of state.projects) {
    const projectItem = document.createElement("li");
    const selected = project.id === state.activeProjectId;
    projectItem.dataset.vogi = "project-row";
    projectItem.dataset.projectId = project.id;
    projectItem.innerHTML = `
      <div class="flex items-center justify-between text-on-surface-variant hover:text-on-surface text-body-sm mb-1 cursor-pointer font-bold px-1 select-none group/proj">
        <div class="flex items-center gap-2">
            <span class="material-symbols-outlined text-[18px] project-icon">folder_open</span>
            <span class="project-name"></span>
        </div>
        <div class="flex items-center gap-0.5">
            <span class="material-symbols-outlined text-[16px] delete-project-icon hover:bg-error/20 hover:text-error rounded opacity-0 group-hover/proj:opacity-100 transition-colors" title="Delete Project">delete</span>
            <span class="material-symbols-outlined text-[16px] add-chat-icon hover:bg-surface-variant rounded opacity-0 group-hover/proj:opacity-100 transition-opacity" title="New Chat">add</span>
            <span class="material-symbols-outlined text-[16px] expand-icon transition-transform hover:bg-surface-variant rounded">expand_more</span>
        </div>
      </div>
      <ul class="flex flex-col gap-0.5 ml-3 pl-2 transition-all"></ul>`;
    projectItem.querySelector(".project-name").textContent = project.name;
    const headerDiv = projectItem.querySelector("div");
    headerDiv.classList.toggle("text-primary", selected);
    const ul = projectItem.querySelector("ul");
    const expandIcon = projectItem.querySelector(".expand-icon");
    const projectIcon = projectItem.querySelector(".project-icon");
    const addChatIcon = projectItem.querySelector(".add-chat-icon");
    
    addChatIcon.addEventListener("click", async (e) => {
        e.stopPropagation();
        selectProject(project.id);
        await createChat("New Chat", true);
        if (state.collapsedProjects.has(project.id)) {
            state.collapsedProjects.delete(project.id);
            renderProjects();
        }
    });
    
    if (state.collapsedProjects.has(project.id)) {
        ul.classList.add("hidden");
        expandIcon.style.transform = "rotate(-90deg)";
        projectIcon.textContent = "folder";
    }
    
    const deleteIcon = projectItem.querySelector(".delete-project-icon");
    
    deleteIcon.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (confirm(`Delete project "${project.name}"? This cannot be undone.`)) {
            await fetch(`/api/projects/${project.id}`, { method: "DELETE" });
            state.projects = state.projects.filter(p => p.id !== project.id);
            if (state.activeProjectId === project.id) {
                state.activeProjectId = state.projects[0]?.id || null;
                state.chats = [];
                state.memories = [];
                if (state.activeProjectId) {
                    await selectProject(state.activeProjectId);
                } else {
                    renderAll();
                }
            } else {
                renderAll();
            }
        }
    });

    headerDiv.addEventListener("click", (e) => {
        if (e.target.closest('.expand-icon') || e.target.closest('.delete-project-icon')) {
            e.stopPropagation();
            if (e.target.closest('.expand-icon')) {
                if (state.collapsedProjects.has(project.id)) {
                    state.collapsedProjects.delete(project.id);
                } else {
                    state.collapsedProjects.add(project.id);
                }
                renderProjects();
            }
            return;
        }
        selectProject(project.id);
    });
    const chatList = projectItem.querySelector("ul");
    for (const chat of state.chats.filter((item) => item.projectId === project.id).slice(0, 6)) {
      const chatItem = document.createElement("li");
      chatItem.dataset.vogi = "chat-row";
      chatItem.dataset.chatId = chat.id;
      chatItem.innerHTML = `
        <a class="flex items-center justify-between px-2 py-1.5 rounded-lg text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors text-body-sm font-body-sm" href="#">
          <span class="truncate pr-2"></span>
          <span class="text-[11px] opacity-70 flex-shrink-0"></span>
        </a>`;
      chatItem.querySelector("a").classList.toggle("bg-surface-container-high", chat.id === state.activeChatId);
      chatItem.querySelector("span").textContent = chat.title;
      chatItem.querySelectorAll("span")[1].textContent = shortTime(chat.updatedAt);
      chatItem.querySelector("a").addEventListener("click", (event) => {
        event.preventDefault();
        selectChat(chat.id);
      });
      chatList.append(chatItem);
    }
    dom.projectList.append(projectItem);
  }
}

function skillIcon(skill) {
  if (skill.name === "upgrade") return "auto_fix_high";
  if (skill.name.includes("web")) return "travel_explore";
  if (skill.name.includes("code")) return "code";
  if (skill.name.includes("memory")) return "memory";
  if (skill.name.includes("shell")) return "terminal";
  if (skill.name.includes("file")) return "folder_open";
  return "neurology";
}

function renderSkills(skills = state.skills) {
  dom.sidebarSkills.innerHTML = "";
  const menuList = dom.skillsDropdown.querySelector("ul");
  menuList.innerHTML = "";
  for (const skill of skills) {
    const li = document.createElement("li");
    const link = document.createElement("a");
    link.className = "flex items-center gap-2 py-1.5 text-body-sm text-on-surface-variant hover:text-primary transition-colors";
    link.href = "#";
    link.append(icon(skillIcon(skill)));
    link.append(document.createTextNode(skill.name));
    link.addEventListener("click", (event) => {
      event.preventDefault();
      dom.composer.value = `${skill.trigger || `/${skill.name}`} `;
      dom.composer.focus();
      toggleSkills(true);
    });
    li.append(link);
    dom.sidebarSkills.append(li);

    const button = document.createElement("button");
    button.className = "w-full flex items-center gap-3 px-3 py-2.5 text-left text-body-sm text-on-surface hover:bg-surface-variant transition-colors group focus:bg-primary/10";
    button.type = "button";
    button.innerHTML = `
      <div class="w-7 h-7 rounded bg-primary/10 border border-primary/20 flex items-center justify-center flex-shrink-0 group-hover:border-primary/50"></div>
      <div class="flex flex-col">
        <span class="font-medium"></span>
        <span class="text-[11px] text-on-surface-variant leading-tight"></span>
      </div>`;
    button.querySelector("div").append(icon(skillIcon(skill), "text-[16px] text-primary"));
    button.querySelector(".font-medium").textContent = skill.name;
    button.querySelector(".leading-tight").textContent = skill.description || skill.instructions || "";
    button.addEventListener("click", () => {
      dom.composer.value = `${skill.trigger || `/${skill.name}`} `;
      dom.composer.focus();
      toggleSkills(false);
    });
    menuList.append(button);
  }
}

function renderPlan(plan = activeChat()?.plan ?? []) {
  dom.executionPlan.innerHTML = "";
  const items = plan.length ? plan : ["Waiting for a task."];
  items.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = `flex items-start gap-3 relative z-10 ${index < items.length - 1 ? "opacity-70" : ""}`;
    row.innerHTML = `
      <div class="w-6 h-6 rounded-full bg-primary/20 border border-primary flex items-center justify-center flex-shrink-0 mt-0.5 relative">
        <span class="w-2 h-2 rounded-full bg-primary ${index === items.length - 1 ? "pulse-dot" : ""}"></span>
      </div>
      <div>
        <p class="font-body-md text-body-md text-primary font-medium leading-tight mb-1"></p>
        <p class="font-body-sm text-body-sm text-on-surface-variant text-[13px] leading-tight"></p>
      </div>`;
    row.querySelector("p").textContent = items.length === 1 && item.includes("Waiting") ? "Idle" : `Step ${index + 1}`;
    row.querySelectorAll("p")[1].textContent = item;
    dom.executionPlan.append(row);
  });
}

function traceLine(entry) {
  if (entry.type === "tool_start") {
    const tool = entry.action?.tool ?? "tool";
    const args = entry.action?.args ?? {};
    let hint = args.path ?? args.url?.replace(/^https?:\/\//, "").slice(0, 60) ?? args.command?.slice(0, 60) ?? args.query?.slice(0, 60) ?? args.name ?? args.pattern ?? "";
    return `⚙️ ${tool}${hint ? ` — ${hint}` : ""}`;
  }
  if (entry.type === "tool") {
    const tool = entry.action?.tool ?? "tool";
    const args = entry.action?.args ?? {};
    const obs  = entry.observation;
    if (tool === "read_file") {
      const chars = typeof obs === "string" ? obs.length : "?";
      return `📄 read — ${args.path ?? ""} (${chars} chars)`;
    }
    if (tool === "write_file" || tool === "append_file") {
      return `💾 ${tool === "write_file" ? "wrote" : "appended"} — ${obs?.written ?? args.path ?? ""} (${obs?.bytes ?? "?"} bytes)`;
    }
    if (tool === "list_dir") {
      return `📁 list_dir — ${args.path ?? ""} → ${Array.isArray(obs) ? obs.length : "?"} items`;
    }
    if (tool === "find_files") {
      return `🔍 find_files — "${args.pattern ?? ""}" → ${Array.isArray(obs) ? obs.length : "?"} files`;
    }
    if (tool === "search_text") {
      return `🔎 search — "${args.query ?? ""}" → ${Array.isArray(obs) ? obs.length : "?"} matches`;
    }
    if (tool === "run_shell") {
      const out = ((obs?.stdout ?? "") + (obs?.stderr ?? "")).trim().slice(0, 80);
      return `💻 shell (exit ${obs?.exitCode ?? "?"}) — ${out || args.command?.slice(0, 60) || ""}`;
    }
    if (tool === "browse_url") {
      const url = (args.url ?? "").replace(/^https?:\/\//, "").slice(0, 60);
      const len = typeof obs === "string" ? obs.length : "?";
      return `🌐 browse — ${url} (${len} chars)`;
    }
    if (tool === "make_dir")             return `📂 make_dir — ${obs?.created ?? args.path ?? ""}`;
    if (tool === "get_system_info")      return `🖥️ system — ${obs?.platform ?? ""} Python ${obs?.python ?? ""}`;
    if (tool === "undo_last_change")     return obs?.undone ? `↩️ undone — ${obs.label}` : `↩️ nothing to undo`;
    if (tool === "create_skill")         return `🛠️ skill created — ${args.name ?? ""}`;
    if (tool === "create_command_tool")  return `🔧 command tool — ${args.name ?? ""}`;
    if (obs?.error)                      return `❌ ${tool} — ${obs.error}`;
    if (typeof obs === "string")         return `✅ ${tool} — ${obs.slice(0, 100)}`;
    if (Array.isArray(obs))              return `✅ ${tool} — ${obs.length} results`;
    const keys = obs && typeof obs === "object" ? Object.keys(obs).join(", ") : "";
    return `✅ ${tool}${keys ? ` — {${keys}}` : ""}`;
  }
  if (entry.type === "error") return `❌ ${entry.error ?? "Unknown error"}`;
  if (entry.type === "final" || entry.type === "done") return "✨ Composing final answer…";
  if (entry.type === "plan") {
    return `📋 Plan: ${(entry.plan ?? []).join(" → ").slice(0, 200)}`;
  }
  if (entry.type === "status" || entry.status) {
    return `💭 ${entry.status ?? ""}`;
  }
  return `ℹ️ ${JSON.stringify(entry).slice(0, 120)}`;
}

function renderLogs(trace = activeChat()?.trace ?? []) {
  dom.processOutput.innerHTML = "";
  const entries = trace.length ? trace : [];
  if (!entries.length) {
    const placeholder = document.createElement("div");
    placeholder.className = "text-on-surface-variant opacity-50 italic";
    placeholder.textContent = "No activity yet. Send a message to see the runtime log.";
    dom.processOutput.append(placeholder);
    return;
  }
  for (const entry of entries.slice(-50)) {
    const line = document.createElement("div");
    let color = "text-primary/70";
    if (entry.type === "error")        color = "text-error";
    else if (entry.type === "tool")    color = "text-[#4ade80]";   // green = done
    else if (entry.type === "tool_start") color = "text-yellow-400"; // yellow = in progress
    else if (entry.type === "plan")    color = "text-sky-400";      // sky = planning
    else if (entry.type === "final")   color = "text-purple-400";   // purple = final
    else if (entry.type === "status")  color = "text-primary/60";   // dim = status
    line.className = `mb-1 font-mono text-[12px] leading-snug break-all ${color}`;
    line.textContent = traceLine(entry);
    dom.processOutput.append(line);
  }
  dom.processOutput.scrollTop = dom.processOutput.scrollHeight;
}

function renderAll() {
  renderProjects();
  renderSkills();
  renderMessages();
  renderPlan();
  renderLogs();
  const rootSpan = document.getElementById("current-project-root");
  if (rootSpan && activeProject()) {
      rootSpan.textContent = activeProject().rootPath || "./src";
      rootSpan.title = activeProject().rootPath || "./src";
  }
}

function toggleSkills(force) {
  const shouldShow = force ?? dom.skillsDropdown.classList.contains("hidden");
  dom.skillsDropdown.classList.toggle("hidden", !shouldShow);
}

function updateSkillMenuFromInput() {
  const value = dom.composer.value.trimStart();
  if (value.startsWith("/") && !value.includes(" ")) {
    const query = value.slice(1).toLowerCase();
    renderSkills(state.skills.filter((skill) => skill.name.toLowerCase().includes(query) || (skill.trigger || "").toLowerCase().includes(query)));
    toggleSkills(true);
  } else {
    toggleSkills(false);
  }
}

async function loadBootstrap() {
  const response = await fetch("/api/bootstrap");
  state.bootstrap = await response.json();
  state.projects = state.bootstrap.projects ?? [];
  state.skills = state.bootstrap.skills ?? [];
  state.activeProjectId = state.bootstrap.activeProjectId ?? state.projects[0]?.id;
  state.chats = state.bootstrap.chats ?? [];
  state.memories = state.bootstrap.memories ?? [];
  if (!state.chats.length && state.activeProjectId) {
    const chat = await createChat("Vogi", false);
    state.activeChatId = chat.id;
  } else {
    state.activeChatId = state.chats[0]?.id;
  }
  const chat = activeChat();
  if (chat && !chat.messages.length) {
    chat.messages.push({ role: "assistant", content: state.bootstrap.app.welcome });
  }
  renderAll();
}

async function selectProject(projectId) {
  const response = await fetch(`/api/projects/${projectId}`);
  const data = await response.json();
  state.activeProjectId = data.project.id;
  state.chats = data.chats ?? [];
  state.memories = data.memories ?? [];
  if (!state.chats.length) await createChat("Vogi", false);
  state.activeChatId = state.chats[0]?.id;
  renderAll();
}

async function selectChat(chatId) {
  const response = await fetch(`/api/chats/${chatId}`);
  const data = await response.json();
  const index = state.chats.findIndex((chat) => chat.id === chatId);
  if (index >= 0) state.chats[index] = data.chat;
  state.activeChatId = chatId;
  renderAll();
}

async function createProject() {
  const name = `Project ${state.projects.length + 1}`;
  const response = await fetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, rootPath: state.bootstrap.projectRoot })
  });
  const data = await response.json();
  state.projects.unshift(data.project);
  state.chats = [data.chat, ...state.chats];
  state.activeProjectId = data.project.id;
  state.activeChatId = data.chat.id;
  data.chat.messages = [{ role: "assistant", content: state.bootstrap.app.welcome }];
  renderAll();
}

async function createChat(title = "New chat", render = true) {
  const response = await fetch(`/api/projects/${state.activeProjectId}/chats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, messages: [{ role: "assistant", content: state.bootstrap?.app?.welcome ?? "New chat ready." }], plan: [], trace: [] })
  });
  const data = await response.json();
  state.chats.unshift(data.chat);
  state.activeChatId = data.chat.id;
  if (render) renderAll();
  return data.chat;
}

async function searchAll(query) {
  if (!query.trim()) {
    await selectProject(state.activeProjectId);
    return;
  }
  const response = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query })
  });
  const data = await response.json();
  state.projects = data.projects?.length ? data.projects : state.projects;
  state.chats = data.chats ?? state.chats;
  renderProjects();
  renderSkills(data.skills?.length ? data.skills : state.skills);
}

async function uploadFiles(files) {
  for (const file of files) {
    const body = new FormData();
    body.append("file", file);
    if (state.activeProjectId) body.append("projectId", state.activeProjectId);
    const response = await fetch("/api/files/upload", { method: "POST", body });
    const data = await response.json();
    activeChat().messages.push({ role: "assistant", content: `Attached ${data.upload.filename} (${data.upload.size} bytes).` });
  }
  renderMessages();
}

function applyEvent(event) {
  const chat = activeChat();
  if (event.type === "status") {
    chat.trace.push(event);
  } else if (event.type === "plan") {
    chat.trace.push(event);
    if (event.plan?.length) chat.plan = event.plan;
  } else if (event.type === "tool_start") {
    chat.trace.push(event);
    if (event.plan?.length) chat.plan = event.plan;
  } else if (event.type === "trace") {
    chat.trace = event.transcript ?? [...chat.trace, event.entry].filter(Boolean);
    if (event.entry?.plan?.length) chat.plan = event.entry.plan;
  } else if (event.type === "final" || event.type === "done") {
    chat.trace = event.transcript?.length ? event.transcript : [...chat.trace, event];
    if (event.plan?.length) chat.plan = event.plan;
  } else if (event.type === "error") {
    chat.trace.push(event);
  } else if (event.type === "tool") {
    chat.trace.push(event);
  }
  renderPlan(chat.plan);
  renderLogs(chat.trace);

  const stepsContainer = document.getElementById("thinking-steps-container");
  if (stepsContainer && state.sending) {
    // Inject plan steps if present and it's a tool_start or plan event
    if (event.plan && event.plan.length && (event.type === "tool_start" || event.type === "plan")) {
       for (const pText of event.plan) {
          const pNode = document.createElement("p");
          pNode.className = "text-[12px] font-code-label text-on-surface-variant truncate whitespace-nowrap mb-0.5 ml-4 text-primary/80";
          pNode.textContent = `• ${pText}`;
          // Only append if it's not already in the container to avoid duplicates
          if (!Array.from(stepsContainer.querySelectorAll("p")).some(el => el.textContent === `• ${pText}`)) {
              stepsContainer.append(pNode);
          }
       }
    }
    
    const p = document.createElement("p");
    p.className = "text-[12px] font-code-label text-on-surface-variant truncate whitespace-nowrap mt-1";
    
    if (event.type === "tool" || event.type === "tool_start") {
       p.classList.add("text-[#4ade80]");
       p.textContent = traceLine(event);
       stepsContainer.append(p);
    } else if (event.type === "error") {
       p.classList.add("text-error");
       p.textContent = traceLine(event);
       stepsContainer.append(p);
    } else if (event.type === "status") {
       p.textContent = traceLine(event);
       stepsContainer.append(p);
    }
    stepsContainer.scrollTop = stepsContainer.scrollHeight;
  }
}

async function readStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalEvent = null;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      applyEvent(event);
      if (event.type === "final" || event.type === "done") finalEvent = event;
    }
  }
  return finalEvent;
}

async function sendTask() {
  if (state.sending) return;
  const task = dom.composer.value.trim();
  if (!task) return;
  let chat = activeChat();
  if (!chat && state.activeProjectId) {
    chat = await createChat("Vogi", false);
  }
  if (!chat) {
    renderLogs([{ type: "error", error: "No active chat is available." }]);
    return;
  }
  chat.messages.push({ role: "user", content: task });
  chat.plan = [];
  chat.trace = [];
  dom.composer.value = "";
  updateSkillMenuFromInput();
  
  state.sending = true;
  setBusy(true);
  
  renderMessages();
  renderPlan(chat.plan);
  renderLogs(chat.trace);
  
  state.controller = new AbortController();
  try {
    const response = await fetch("/api/agent/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: state.controller.signal,
      body: JSON.stringify({
        task,
        history: chat.messages.slice(0, -1),
        projectRoot: activeProject()?.rootPath,
        projectId: state.activeProjectId,
        chatId: state.activeChatId,
        planningMode: state.planningMode
      })
    });
    const result = await readStream(response);
    chat.messages.push({ role: "assistant", content: result?.final ?? "Agent finished without a final response.", files: result?.files ?? [] });
  } catch (error) {
    chat.messages.push({ role: "assistant", content: error.name === "AbortError" ? "Cancelled." : error.message });
    chat.trace.push({ type: "error", error: error.message });
  } finally {
    state.sending = false;
    setBusy(false);
    renderAll();
  }
}

async function openSettings() {
  const models = await (await fetch("/api/models")).json();
  document.querySelector("#current-model-name").textContent = models.model ?? "local";
  const connected = Array.from(dom.settingsModal.querySelectorAll("span")).find((span) => span.textContent.includes("CONNECTED") || span.textContent.includes("OFFLINE") || span.textContent.includes("ollama"));
  if (connected) connected.textContent = models.error ? "OFFLINE" : `${models.provider}: ${models.model}`;
  dom.settingsModal.classList.remove("hidden");
}

async function saveSettings() {
  const key = dom.settingsModal.querySelector("input[type='password']")?.value ?? "";
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: key ? "openai" : "ollama", openaiApiKey: key })
  });
  dom.settingsModal.classList.add("hidden");
}

dom.newProject.addEventListener("click", createProject);
dom.openProject?.addEventListener("click", async () => {
  const res = await fetch("/api/select-folder", { method: "POST", body: JSON.stringify({}) });
  const data = await res.json();
  if (data.cancelled || !data.path) return;
  const name = data.path.split("\\").pop() || "Project";
  const response = await fetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, rootPath: data.path })
  });
  const projData = await response.json();
  state.projects.unshift(projData.project);
  state.chats = [projData.chat, ...state.chats];
  state.activeProjectId = projData.project.id;
  state.activeChatId = projData.chat.id;
  if (projData.chat && !projData.chat.messages?.length && state.bootstrap) {
    projData.chat.messages = [{ role: "assistant", content: state.bootstrap.app.welcome }];
  }
  renderAll();
});
dom.newChat.addEventListener("click", (event) => {
  event.preventDefault();
  createChat();
});
dom.searchButton.addEventListener("click", () => {
  dom.searchButton.classList.add("hidden");
  dom.searchInput.classList.remove("hidden");
  dom.searchInput.focus();
});
dom.searchInput.addEventListener("input", () => searchAll(dom.searchInput.value));
dom.skillsButton.addEventListener("click", () => {
  dom.composer.value = "/";
  dom.composer.focus();
  updateSkillMenuFromInput();
});
dom.attachButton.addEventListener("click", () => dom.fileInput.click());
dom.fileInput.addEventListener("change", () => uploadFiles(Array.from(dom.fileInput.files ?? [])));
dom.composer.addEventListener("input", updateSkillMenuFromInput);
dom.composer.addEventListener("keydown", (event) => {
  if (event.key === "Escape") toggleSkills(false);
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendTask();
  }
});
dom.planningToggle.addEventListener("click", () => {
  state.planningMode = !state.planningMode;
  dom.planningToggle.classList.toggle("border-primary", state.planningMode);
});
dom.send.addEventListener("click", (event) => {
  event.preventDefault();
  sendTask();
});
dom.stop.addEventListener("click", (event) => {
  event.preventDefault();
  if (state.controller) {
    state.controller.abort();
    state.controller = null;
  }
  const chat = activeChat();
  if (chat) {
    chat.trace.push({ type: "status", status: "Stopped by user." });
    chat.messages.push({ role: "assistant", content: "⛔ Stopped." });
  }
  state.sending = false;
  setBusy(false);
  renderAll();
});
document.addEventListener("click", (event) => {
  if (!dom.skillsDropdown.contains(event.target) && !dom.composer.contains(event.target) && !dom.skillsButton.contains(event.target)) {
    toggleSkills(false);
  }
  const modelDropdown = document.querySelector("#model-dropdown");
  const modelSelectBtn = document.querySelector("#model-select-btn");
  if (modelSelectBtn && modelDropdown && !modelSelectBtn.contains(event.target) && !modelDropdown.contains(event.target)) {
    modelDropdown.classList.add("hidden");
  }
  const permsDropdown = document.querySelector("#permissions-dropdown");
  const permsBtn = document.querySelector("#permissions-btn");
  if (permsBtn && permsDropdown && !permsBtn.contains(event.target) && !permsDropdown.contains(event.target)) {
    permsDropdown.classList.add("hidden");
  }
});
for (const link of Array.from(document.querySelectorAll("a")).filter((item) => item.textContent.includes("Settings"))) {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    openSettings();
  });
}
for (const button of dom.settingsModal.querySelectorAll("button")) {
  if (button.textContent.includes("Cancel") || button.textContent.includes("close")) {
    button.addEventListener("click", () => dom.settingsModal.classList.add("hidden"));
  }
  if (button.textContent.includes("Save Changes")) button.addEventListener("click", saveSettings);
}

const modelSelectBtn = document.querySelector("#model-select-btn");
const modelDropdown = document.querySelector("#model-dropdown");
const modelList = document.querySelector("#model-list");
const currentModelName = document.querySelector("#current-model-name");

modelSelectBtn?.addEventListener("click", async () => {
  modelDropdown.classList.toggle("hidden");
  if (!modelDropdown.classList.contains("hidden")) {
    try {
      const res = await fetch("/api/models");
      const data = await res.json();
      modelList.innerHTML = "";
      let activeModel = data.model || "Unknown";
      if (currentModelName) currentModelName.textContent = activeModel;
      for (const model of data.models || []) {
        const isActive = model === activeModel;
        const li = document.createElement("li");
        li.innerHTML = `<button type="button" class="w-full flex items-center justify-between px-3 py-2 text-body-sm text-on-surface hover:bg-surface-variant transition-colors ${isActive ? "bg-primary/10 text-primary font-semibold" : ""}">
          <span>${model}</span>
          ${isActive ? '<span class="text-[10px] bg-primary text-on-primary px-1.5 py-0.5 rounded font-bold">ACTIVE</span>' : ""}
        </button>`;
        li.querySelector("button").addEventListener("click", async () => {
          if (isActive) { modelDropdown.classList.add("hidden"); return; }
          
          if (model.toLowerCase().includes("gemma") && !localStorage.getItem("gemma_started")) {
            modelDropdown.classList.add("hidden");
            const gemmaModal = document.getElementById("gemma-start-modal");
            if (gemmaModal) {
              gemmaModal.classList.remove("hidden");
              
              const handleCancel = () => { gemmaModal.classList.add("hidden"); };
              const closeBtn = document.getElementById("gemma-close-btn");
              const cancelBtn = document.getElementById("gemma-cancel-btn");
              if (closeBtn) closeBtn.onclick = handleCancel;
              if (cancelBtn) cancelBtn.onclick = handleCancel;
              
              const startBtn = document.getElementById("gemma-start-btn");
              if (startBtn) {
                startBtn.onclick = async () => {
                  gemmaModal.classList.add("hidden");
                  localStorage.setItem("gemma_started", "true");
                  
                  if (currentModelName) currentModelName.textContent = model;
                  
                  try {
                    const switchRes = await fetch("/api/model", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ model: model, provider: "ollama" })
                    });
                    const switched = await switchRes.json();
                    if (currentModelName) currentModelName.textContent = switched.model || model;
                  } catch(err) {
                    console.error("Model switch failed", err);
                  }
                  
                  const chat = activeChat();
                  if (chat) {
                    if (!chat.trace) chat.trace = [];
                    chat.trace.push({
                      step: chat.trace.length + 1,
                      type: "status",
                      status: "Starting Gemma model in the background (Ollama)..."
                    });
                    renderLogs(chat.trace);
                  }
                  
                  try {
                    await fetch("/api/ollama/start", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ model: model })
                    });
                  } catch(err) {
                    console.error("Failed to start Gemma model in background", err);
                  }
                };
              }
            }
            return;
          }
          
          currentModelName.textContent = model;
          modelDropdown.classList.add("hidden");
          try {
            const switchRes = await fetch("/api/model", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ model: model, provider: data.provider })
            });
            const switched = await switchRes.json();
            if (currentModelName) currentModelName.textContent = switched.model || model;
          } catch(err) {
            console.error("Model switch failed", err);
            if (currentModelName) currentModelName.textContent = activeModel;
          }
        });
        modelList.append(li);
      }
    } catch (e) {
      console.error("Failed to load models", e);
      modelList.innerHTML = "<li class='px-3 py-2 text-error text-sm'>Failed to load models.</li>";
    }
  }
});

const permsBtn = document.querySelector("#permissions-btn");
const permsDropdown = document.querySelector("#permissions-dropdown");
const currentPerms = document.querySelector("#current-permission");

permsBtn?.addEventListener("click", () => {
  permsDropdown.classList.toggle("hidden");
});

permsDropdown?.querySelectorAll("button").forEach(btn => {
  btn.addEventListener("click", (e) => {
    currentPerms.textContent = e.target.textContent;
    permsDropdown.classList.add("hidden");
  });
});

await loadBootstrap();
toggleSkills(false);

fetch("/api/models").then(res => res.json()).then(data => {
  if (currentModelName && data.model) {
    currentModelName.textContent = data.model;
  }
}).catch(console.error);

const copyBtn = document.getElementById("copy-output-btn");
copyBtn?.addEventListener("click", () => {
  if (!dom.processOutput) return;
  const text = dom.processOutput.innerText;
  navigator.clipboard.writeText(text).then(() => {
    const iconSpan = copyBtn.querySelector(".material-symbols-outlined");
    if (iconSpan) {
      iconSpan.textContent = "check";
      setTimeout(() => {
        iconSpan.textContent = "content_copy";
      }, 2000);
    }
  }).catch(err => {
    console.error("Failed to copy text: ", err);
  });
});
