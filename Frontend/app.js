const els = {
  appName: document.querySelector("#appName"),
  appTagline: document.querySelector("#appTagline"),
  projectList: document.querySelector("#projectList"),
  skillList: document.querySelector("#skillList"),
  skillsMenu: document.querySelector("#skillsMenu"),
  chatLog: document.querySelector("#chatLog"),
  chatForm: document.querySelector("#chatForm"),
  chatInput: document.querySelector("#chatInput"),
  chatTitle: document.querySelector("#chatTitle"),
  runtimeStatus: document.querySelector("#runtimeStatus"),
  runStatus: document.querySelector("#runStatus"),
  runStatusText: document.querySelector("#runStatusText"),
  planList: document.querySelector("#planList"),
  runtimeLogs: document.querySelector("#runtimeLogs"),
  stepCount: document.querySelector("#stepCount"),
  toolTrace: document.querySelector("#toolTrace"),
  modelSelect: document.querySelector("#modelSelect"),
  providerSelect: document.querySelector("#providerSelect"),
  ollamaUrlInput: document.querySelector("#ollamaUrlInput"),
  openaiKeyInput: document.querySelector("#openaiKeyInput"),
  projectRootInput: document.querySelector("#projectRootInput"),
  projectRootLabel: document.querySelector("#projectRootLabel"),
  settingsDialog: document.querySelector("#settingsDialog"),
  planningToggle: document.querySelector("#planningToggle"),
  sendButton: document.querySelector("#sendButton"),
  cancelButton: document.querySelector("#cancelButton")
};

const storageKey = "vogi-standalone-state-v1";
let controller = null;
let bootstrap = null;
let state = loadState();

state.filteredSkills = [];
state.selectedSkillIndex = -1;

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey));
    if (saved?.chats?.length) return saved;
  } catch {}
  const chat = createChat("Vogi");
  return { activeChatId: chat.id, projectRoot: "", chats: [chat] };
}

function saveState() {
  localStorage.setItem(storageKey, JSON.stringify(state));
}

function createChat(title = "New Chat") {
  return { id: crypto.randomUUID(), title, messages: [], plan: [], trace: [] };
}

function activeChat() {
  return state.chats.find((chat) => chat.id === state.activeChatId) ?? state.chats[0];
}

function setBusy(value) {
  els.sendButton.disabled = value;
  els.chatInput.disabled = value;
  els.cancelButton.classList.toggle("hidden", !value);
  els.runStatus.classList.toggle("hidden", !value);
}

function addMessage(role, content) {
  const chat = activeChat();
  chat.messages.push({ role, content });
  if (role === "user" && chat.title === "New Chat") {
    chat.title = content.trim().replace(/\s+/g, " ").slice(0, 42) || "New Chat";
  }
  saveState();
  render();
}

function render() {
  const chat = activeChat();
  els.chatTitle.textContent = chat.title;
  els.projectRootInput.value = state.projectRoot;
  els.projectRootLabel.textContent = state.projectRoot ? `Root: ${state.projectRoot}` : "";
  renderMessages(chat.messages);
  renderPlan(chat.plan);
  renderLogs(chat.trace);
  els.toolTrace.textContent = JSON.stringify(chat.trace ?? [], null, 2);
}

function renderMessages(messages) {
  els.chatLog.innerHTML = "";
  for (const message of messages) {
    const row = document.createElement("article");
    row.className = `message ${message.role}`;
    const role = document.createElement("div");
    role.className = "message-role";
    role.textContent = message.role === "user" ? "You" : "Vogi";
    const body = document.createElement("div");
    body.textContent = message.content;
    row.append(role, body);
    els.chatLog.append(row);
  }
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
}

function renderPlan(plan) {
  const items = Array.isArray(plan) && plan.length ? plan : ["Waiting for a task."];
  els.planList.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    els.planList.append(li);
  }
}

function shortObservation(observation) {
  if (observation?.stdout) return observation.stdout;
  if (observation?.error) return observation.error;
  return JSON.stringify(observation ?? {}).slice(0, 360);
}

function renderLogs(trace) {
  const steps = Array.isArray(trace) ? trace : [];
  els.stepCount.textContent = `${steps.length} step${steps.length === 1 ? "" : "s"}`;
  els.runtimeLogs.innerHTML = "";
  if (!steps.length) {
    const row = document.createElement("article");
    row.className = "log-row";
    row.innerHTML = "<strong>Idle</strong><p>Runtime events will appear here while Vogi works.</p>";
    els.runtimeLogs.append(row);
    return;
  }
  for (const entry of steps) {
    const row = document.createElement("article");
    row.className = "log-row";
    const title = document.createElement("strong");
    title.textContent = entry.type === "tool" || entry.type === "tool_start"
      ? `${entry.step}. ${entry.action?.tool ?? "tool"}`
      : `${entry.step ?? ""} ${entry.type}`.trim();
    const detail = document.createElement("p");
    detail.textContent = entry.type === "tool" ? shortObservation(entry.observation) : entry.status ?? entry.error ?? "";
    row.append(title, detail);
    els.runtimeLogs.append(row);
  }
}

function renderProjects(projects = []) {
  els.projectList.innerHTML = "";
  for (const project of projects) {
    for (const item of project.items ?? []) {
      const row = document.createElement("article");
      row.className = "project-item";
      row.innerHTML = `<strong></strong><span></span>`;
      row.querySelector("strong").textContent = item.title;
      row.querySelector("span").textContent = `${project.folder} · ${item.updated}`;
      els.projectList.append(row);
    }
  }
}

function renderSkills() {
  const skills = bootstrap?.skills ?? [];
  els.skillList.innerHTML = "";
  els.skillsMenu.innerHTML = "";
  
  // Sidebar skills
  for (const skill of skills) {
    const row = document.createElement("article");
    row.className = "skill-item";
    row.innerHTML = `<strong></strong><span></span>`;
    row.querySelector("strong").textContent = skill.name;
    row.querySelector("span").textContent = skill.description;
    els.skillList.append(row);
  }

  // Dropdown skills
  state.filteredSkills.forEach((skill, index) => {
    const isSelected = index === state.selectedSkillIndex;
    const button = document.createElement("button");
    button.className = `skill-menu-button ${isSelected ? "selected" : ""}`;
    button.type = "button";
    button.innerHTML = `<strong></strong><span></span>`;
    button.querySelector("strong").textContent = skill.name;
    button.querySelector("span").textContent = skill.description;
    button.addEventListener("click", () => {
      els.chatInput.value = `/${skill.name.toLowerCase().replace(/\s+/g, "_")} `;
      els.skillsMenu.classList.add("hidden");
      els.chatInput.focus();
    });
    if (isSelected) {
      button.scrollIntoView({ block: "nearest" });
    }
    els.skillsMenu.append(button);
  });
}

function toggleSkills(force) {
  const shouldShow = force ?? els.skillsMenu.classList.contains("hidden");
  els.skillsMenu.classList.toggle("hidden", !shouldShow);
}

function updateSkillMenuFromInput() {
  const value = els.chatInput.value.trimStart();
  const skills = bootstrap?.skills ?? [];
  if (value.startsWith("/") && !value.includes(" ")) {
    const query = value.slice(1).toLowerCase();
    state.filteredSkills = skills.filter((skill) => 
      skill.name.toLowerCase().includes(query) || 
      (skill.trigger || "").toLowerCase().includes(query)
    );
    state.selectedSkillIndex = state.filteredSkills.length > 0 ? 0 : -1;
    renderSkills();
    toggleSkills(true);
  } else {
    state.filteredSkills = [];
    state.selectedSkillIndex = -1;
    toggleSkills(false);
  }
}

async function loadBootstrap() {
  const response = await fetch("/api/bootstrap");
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error ?? "Bootstrap failed.");
  bootstrap = data;
  els.appName.textContent = data.app.name;
  els.appTagline.textContent = data.app.tagline;
  els.providerSelect.value = data.runtime.provider;
  els.ollamaUrlInput.value = data.runtime.ollamaUrl;
  if (!state.projectRoot) state.projectRoot = data.projectRoot;
  if (!activeChat().messages.length) activeChat().messages.push({ role: "assistant", content: data.app.welcome });
  renderProjects(data.projects);
  state.filteredSkills = data.skills ?? [];
  renderSkills();
  saveState();
  render();
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error ?? "Runtime offline");
    els.runtimeStatus.textContent = `${data.provider}: ${data.model}`;
    els.runtimeStatus.classList.remove("error");
  } catch (error) {
    els.runtimeStatus.textContent = error.message;
    els.runtimeStatus.classList.add("error");
  }
}

async function loadModels() {
  const response = await fetch("/api/models");
  const data = await response.json();
  els.modelSelect.innerHTML = "";
  const models = data.models?.length ? data.models : [data.model].filter(Boolean);
  for (const model of models) {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    option.selected = model === data.model;
    els.modelSelect.append(option);
  }
}

async function loadSkills() {
  const response = await fetch("/api/skills");
  const data = await response.json();
  const configured = bootstrap?.skills ?? [];
  const saved = (data.skills ?? []).map((skill) => ({ name: skill.name, description: skill.description || "Saved local skill" }));
  renderSkills([...configured, ...saved]);
}

function applyStreamEvent(chat, event) {
  if (event.type === "status") {
    els.runStatusText.textContent = event.status;
    chat.trace = [...(chat.trace ?? []), { step: event.step ?? "", type: "status", status: event.status }];
  } else if (event.type === "tool_start") {
    els.runStatusText.textContent = event.status;
    chat.plan = event.plan?.length ? event.plan : chat.plan;
    chat.trace = [...(chat.trace ?? []), event];
  } else if (event.type === "trace") {
    chat.trace = event.transcript ?? [...(chat.trace ?? []), event.entry].filter(Boolean);
    if (event.entry?.plan?.length) chat.plan = event.entry.plan;
  } else if (event.type === "final" || event.type === "done") {
    if (event.plan?.length) chat.plan = event.plan;
    chat.trace = event.transcript ?? chat.trace ?? [];
  } else if (event.type === "error") {
    chat.trace = [...(chat.trace ?? []), { type: "error", error: event.error }];
  }
  saveState();
  render();
}

async function readStream(response, chat) {
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
      applyStreamEvent(chat, event);
      if (event.type === "final" || event.type === "done") finalEvent = event;
    }
  }
  if (buffer.trim()) {
    const event = JSON.parse(buffer);
    applyStreamEvent(chat, event);
    if (event.type === "final" || event.type === "done") finalEvent = event;
  }
  return finalEvent;
}

els.chatInput.addEventListener("input", updateSkillMenuFromInput);
els.chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    toggleSkills(false);
    state.selectedSkillIndex = -1;
    renderSkills();
  }

  const isDropdownVisible = !els.skillsMenu.classList.contains("hidden");
  if (isDropdownVisible && state.filteredSkills.length > 0) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      state.selectedSkillIndex = (state.selectedSkillIndex + 1) % state.filteredSkills.length;
      renderSkills();
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      state.selectedSkillIndex = (state.selectedSkillIndex - 1 + state.filteredSkills.length) % state.filteredSkills.length;
      renderSkills();
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      if (state.selectedSkillIndex >= 0) {
        event.preventDefault();
        const skill = state.filteredSkills[state.selectedSkillIndex];
        els.chatInput.value = `${skill.trigger || `/${skill.name}`} `;
        toggleSkills(false);
        state.selectedSkillIndex = -1;
        return;
      }
    }
  }
});

els.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const task = els.chatInput.value.trim();
  if (!task) return;
  controller = new AbortController();
  addMessage("user", task);
  els.chatInput.value = "";
  const chat = activeChat();
  chat.plan = ["Read request.", "Choose tools or answer directly.", "Return final result."];
  chat.trace = [];
  setBusy(true);
  render();
  try {
    const response = await fetch("/api/agent/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({ task, history: chat.messages.slice(0, -1), projectRoot: state.projectRoot, planningMode: els.planningToggle.checked })
    });
    if (!response.ok) throw new Error("Agent stream failed.");
    const data = await readStream(response, chat);
    chat.messages.push({ role: "assistant", content: data?.final ?? "Agent finished without a final response." });
  } catch (error) {
    chat.messages.push({ role: "assistant", content: error.name === "AbortError" ? "Cancelled." : error.message });
  } finally {
    setBusy(false);
    saveState();
    render();
  }
});

document.querySelector("#newChatButton").addEventListener("click", () => {
  const chat = createChat();
  chat.messages.push({ role: "assistant", content: bootstrap?.app?.welcome ?? "New chat ready." });
  state.chats.unshift(chat);
  state.activeChatId = chat.id;
  saveState();
  render();
});

document.querySelector("#settingsButton").addEventListener("click", () => els.settingsDialog.showModal());
document.querySelector("#skillsMenuButton").addEventListener("click", () => els.skillsMenu.classList.toggle("hidden"));
document.querySelector("#refreshBootstrapButton").addEventListener("click", loadBootstrap);
document.querySelector("#refreshSkillsButton").addEventListener("click", loadSkills);
document.querySelector("#refreshModelsButton").addEventListener("click", loadModels);
document.querySelector("#clearLogsButton").addEventListener("click", () => {
  const chat = activeChat();
  chat.trace = [];
  chat.plan = [];
  saveState();
  render();
});
els.cancelButton.addEventListener("click", () => controller?.abort());

document.querySelector("#saveRootButton").addEventListener("click", () => {
  state.projectRoot = els.projectRootInput.value.trim() || bootstrap?.projectRoot || "";
  saveState();
  render();
});

document.querySelector("#browseRootButton").addEventListener("click", async () => {
  const response = await fetch("/api/select-folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ startPath: state.projectRoot })
  });
  const data = await response.json();
  if (data.path) {
    state.projectRoot = data.path;
    saveState();
    render();
  }
});

document.querySelector("#diagnoseButton").addEventListener("click", async () => {
  const response = await fetch("/api/runtime/diagnose");
  const data = await response.json();
  addMessage("assistant", data.ok ? `Runtime diagnostic passed in ${data.elapsedMs} ms. Response: ${data.response || "ready"}` : `Runtime diagnostic failed: ${data.error}`);
});

document.querySelector("#undoButton").addEventListener("click", async () => {
  const response = await fetch("/api/agent/undo", { method: "POST" });
  const data = await response.json();
  addMessage("assistant", data.undone ? `Undo complete: ${data.label}` : data.message);
});

document.querySelector("#saveSettingsButton").addEventListener("click", async () => {
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider: els.providerSelect.value,
      model: els.modelSelect.value,
      ollamaUrl: els.ollamaUrlInput.value,
      openaiApiKey: els.openaiKeyInput.value
    })
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error ?? "Settings failed.");
  els.settingsDialog.close();
  await loadHealth();
  await loadModels();
});

document.querySelector("#attachButton").addEventListener("click", () => {
  addMessage("assistant", "Attach is ready in the UI. File upload handling will be routed through the backend next; for now, use a project path in your prompt.");
});

await loadBootstrap();
await loadHealth();
await loadModels();
await loadSkills();

