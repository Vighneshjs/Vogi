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
  sidebarSkillsToggle: q("sidebar-skills-toggle"),
  sidebarSkillsIcon: q("sidebar-skills-icon"),
  chatScroll: q("chat-scroll"),
  skillsDropdown: q("skills-dropdown"),
  skillsButton: q("skills-button"),
  attachButton: q("attach-button"),
  fileInput: q("file-input"),
  attachmentChips: q("attachment-chips"),
  composer: q("composer"),
  planningToggle: q("planning-toggle"),
  send: q("send"),
  stop: q("stop"),
  runBadge: q("run-badge"),
  executionPlan: q("execution-plan"),
  processOutput: q("process-output"),
  settingsModal: q("settings-modal"),
  browserSessionBadge: q("browser-session-badge"),
  browserSessionMessage: q("browser-session-message"),
  browserSessionStart: q("browser-session-start"),
  browserSessionClose: q("browser-session-close")
};

const state = {
  bootstrap: null,
  projects: [],
  chats: [],
  memories: [],
  skills: [],
  activeProjectId: null,
  activeChatId: null,
  selectedSkillIndex: -1,
  filteredSkills: [],
  planningMode: false,
  permissionMode: "full",
  sidebarSkillsOpen: false,
  pendingAttachments: [],
  sending: false,
  controller: null,
  collapsedProjects: new Set()
};

function text(value) {
  return String(value ?? "");
}

function escapeHtml(value) {
  return text(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function inlineMarkdown(value) {
  let html = escapeHtml(value);
  html = html.replace(/`([^`]+)`/g, '<code class="px-1.5 py-0.5 rounded bg-surface-container-high border border-outline-variant text-[0.9em] font-code-label text-primary">$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-on-surface">$1</strong>');
  html = html.replace(/(^|\s)([\w.-]+\/(?:[\w .@()+-]+\/)*[\w .@()+-]+\.[A-Za-z0-9]{1,8})(?=$|[\s,.;:)])/g, '$1<code class="px-1.5 py-0.5 rounded bg-surface-container-high border border-outline-variant text-[0.9em] font-code-label text-tertiary">$2</code>');
  return html;
}

function looksLikeCodeLine(line, language = "text") {
  const stripped = text(line).trim();
  if (!stripped) return true;
  if (/^(\.|#|\{|}|<|<\/|const |let |var |function |class |import |export |def |async def |return |if |for |while |\$|npm |python |uvicorn |git |@)/.test(stripped)) return true;
  if (/[;{}]|=>|==|===|&&|\|\|/.test(stripped)) return true;
  if (language === "css" && /^[a-zA-Z-]+\s*:\s*[^;]+;?\s*(\/\*.*\*\/)?$/.test(stripped)) return true;
  if (["json", "javascript", "typescript"].includes(language) && /^["']?[\w-]+["']?\s*:/.test(stripped)) return true;
  return false;
}

function fenceLooseCodeSections(content) {
  const source = text(content);
  if (source.includes("```")) return source;
  const labels = {
    css: "css",
    html: "html",
    javascript: "javascript",
    js: "javascript",
    typescript: "typescript",
    ts: "typescript",
    python: "python",
    powershell: "powershell",
    shell: "bash",
    bash: "bash",
    json: "json"
  };
  const lines = source.split("\n");
  const output = [];
  let index = 0;
  while (index < lines.length) {
    const labelMatch = lines[index].match(/^\s*(CSS|HTML|JavaScript|JS|TypeScript|TS|Python|PowerShell|Shell|Bash|JSON)\s*:\s*$/i);
    if (!labelMatch) {
      output.push(lines[index]);
      index += 1;
      continue;
    }
    const language = labels[labelMatch[1].toLowerCase()];
    let probe = index + 1;
    while (probe < lines.length && !lines[probe].trim()) probe += 1;
    if (probe >= lines.length || !looksLikeCodeLine(lines[probe], language)) {
      output.push(lines[index]);
      index += 1;
      continue;
    }
    output.push(lines[index], `\`\`\`${language}`);
    index += 1;
    let collected = false;
    let braceBalance = 0;
    while (index < lines.length) {
      const line = lines[index];
      const stripped = line.trim();
      const nextLabel = /^\s*(CSS|HTML|JavaScript|JS|TypeScript|TS|Python|PowerShell|Shell|Bash|JSON|Options|Result|Output|Explanation)\s*:\s*$/i.test(line);
      const numberedSection = /^\s*\d+[.)]\s+[A-Z][^{};]*$/.test(line);
      if (collected && stripped && (nextLabel || numberedSection) && braceBalance <= 0 && !looksLikeCodeLine(line, language)) break;
      if (collected && !stripped) {
        const nextNonBlank = lines.slice(index + 1).find((candidate) => candidate.trim())?.trim() || "";
        if (nextNonBlank && /^(\d+[.)]\s+)?[A-Z][^{};]*:?$/.test(nextNonBlank) && braceBalance <= 0 && !looksLikeCodeLine(nextNonBlank, language)) break;
      }
      output.push(line);
      if (stripped) {
        collected = true;
        braceBalance += (line.match(/{/g) || []).length - (line.match(/}/g) || []).length;
      }
      if (language === "css" && collected && stripped === "}" && braceBalance <= 0) {
        index += 1;
        break;
      }
      index += 1;
    }
    output.push("```");
  }
  return output.join("\n");
}

function renderMarkdown(content) {
  const fragment = document.createDocumentFragment();
  const source = fenceLooseCodeSections(content).replaceAll("\r\n", "\n").replaceAll("\u2014", "-");
  const parts = source.split(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g);

  function appendRichText(block) {
    const lines = block.split("\n");
    let list = null;
    const flushList = () => {
      if (list) {
        fragment.append(list);
        list = null;
      }
    };
    for (const rawLine of lines) {
      const line = rawLine.trimEnd();
      if (!line.trim()) {
        flushList();
        continue;
      }
      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        flushList();
        const level = Math.min(3, heading[1].length);
        const node = document.createElement(level === 1 ? "h2" : level === 2 ? "h3" : "h4");
        node.className = level === 1
          ? "mt-2 mb-2 text-[18px] font-semibold text-on-surface"
          : "mt-3 mb-1 text-[15px] font-semibold text-on-surface";
        node.innerHTML = inlineMarkdown(heading[2]);
        fragment.append(node);
        continue;
      }
      const bullet = line.match(/^\s*[-*]\s+(.+)$/);
      const numbered = line.match(/^\s*\d+[.)]\s+(.+)$/);
      if (bullet || numbered) {
        if (!list) {
          list = document.createElement(numbered ? "ol" : "ul");
          list.className = numbered ? "list-decimal pl-5 my-2 space-y-1" : "list-disc pl-5 my-2 space-y-1";
        }
        const item = document.createElement("li");
        item.className = "pl-1 leading-relaxed";
        item.innerHTML = inlineMarkdown((bullet || numbered)[1]);
        list.append(item);
        continue;
      }
      flushList();
      const p = document.createElement("p");
      p.className = "leading-relaxed my-2";
      p.innerHTML = inlineMarkdown(line);
      fragment.append(p);
    }
    flushList();
  }

  for (let index = 0; index < parts.length; index += 3) {
    appendRichText(parts[index] || "");
    if (index + 2 < parts.length) {
      const language = parts[index + 1] || "text";
      const code = parts[index + 2] || "";
      const wrapper = document.createElement("div");
      wrapper.className = "my-3 overflow-hidden rounded-lg border border-outline-variant bg-[#111318]";
      wrapper.innerHTML = `
        <div class="flex items-center justify-between px-3 py-2 border-b border-outline-variant/70 bg-surface-container-high">
          <span class="text-[11px] uppercase tracking-wide text-on-surface-variant font-code-label"></span>
          <button type="button" class="copy-code text-[11px] text-on-surface-variant hover:text-on-surface">Copy</button>
        </div>
        <pre class="overflow-x-auto p-3 text-[12px] leading-relaxed text-[#e5e7eb] font-code-label"><code></code></pre>
      `;
      wrapper.querySelector("span").textContent = language;
      wrapper.querySelector("code").textContent = code.trim();
      wrapper.querySelector(".copy-code").addEventListener("click", async (event) => {
        await navigator.clipboard?.writeText(code.trim()).catch(() => {});
        event.currentTarget.textContent = "Copied";
        setTimeout(() => { event.currentTarget.textContent = "Copy"; }, 1200);
      });
      fragment.append(wrapper);
    }
  }
  return fragment;
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

function displayPath(path) {
  const value = text(path).replaceAll("\\", "/");
  const marker = "vogi_agent/";
  const markerIndex = value.toLowerCase().indexOf(marker);
  return markerIndex >= 0 ? value.slice(markerIndex) : value;
}

function fileName(path) {
  return displayPath(path).split("/").filter(Boolean).pop() || displayPath(path);
}

function changesFromTrace(trace = []) {
  const changes = new Map();
  for (const entry of trace) {
    const action = entry.action ?? {};
    if (entry.type !== "tool" || !["write_file", "append_file"].includes(action.tool)) continue;
    const observation = entry.observation ?? {};
    if (observation.error) continue;
    const path = observation.written ?? observation.path ?? action.args?.path;
    if (!path) continue;
    const key = text(path);
    const current = changes.get(key) ?? { path: key, additions: 0, deletions: 0, operations: 0 };
    current.additions += Number(observation.additions ?? 0);
    current.deletions += Number(observation.deletions ?? 0);
    current.operations += 1;
    changes.set(key, current);
  }
  return Array.from(changes.values());
}

function normalizeChanges(message = {}) {
  if (Array.isArray(message.changes) && message.changes.length) return message.changes;
  if (Array.isArray(message.files) && message.files.length) {
    return message.files.map((item) => typeof item === "string" ? { path: item, additions: 0, deletions: 0 } : item);
  }
  return [];
}

async function undoLastChange(button) {
  if (button.disabled) return;
  button.disabled = true;
  button.innerHTML = `<span class="material-symbols-outlined text-[14px] animate-spin">sync</span> Undoing`;
  try {
    const res = await fetch("/api/agent/undo", { method: "POST" });
    const data = await res.json();
    if (data.undone) {
      button.innerHTML = `<span class="material-symbols-outlined text-[14px]">check</span> Undone`;
      button.classList.add("text-[#4ade80]");
    } else {
      button.innerHTML = `<span class="material-symbols-outlined text-[14px]">error</span> ${data.message || "Failed"}`;
      button.classList.add("text-error");
    }
  } catch {
    button.innerHTML = `<span class="material-symbols-outlined text-[14px]">error</span> Error`;
    button.classList.add("text-error");
  }
}

function renderChangeSummaryCard(changes, { live = false } = {}) {
  if (!changes.length) return null;
  const totalAdditions = changes.reduce((sum, item) => sum + Number(item.additions ?? 0), 0);
  const totalDeletions = changes.reduce((sum, item) => sum + Number(item.deletions ?? 0), 0);
  const card = document.createElement("div");
  card.className = live
    ? "mt-3 w-full max-w-xl rounded-lg border border-outline-variant bg-surface-container-low overflow-hidden shadow-sm"
    : "mt-4 w-full max-w-xl rounded-lg border border-outline-variant bg-surface-container-low overflow-hidden shadow-sm";
  card.dataset.vogi = live ? "live-change-summary" : "change-summary";
  card.innerHTML = `
    <div class="flex items-center justify-between gap-3 px-4 py-3">
      <div class="flex items-center gap-3 min-w-0">
        <div class="w-10 h-10 rounded-lg bg-surface-container-high flex items-center justify-center border border-outline-variant flex-shrink-0">
          <span class="material-symbols-outlined text-[20px] text-on-surface">library_add_check</span>
        </div>
        <div class="min-w-0">
          <div class="font-title-md text-title-md text-on-surface text-[15px]">${live ? "Editing files now" : `Edited ${changes.length} ${changes.length === 1 ? "file" : "files"}`}</div>
          <div class="font-code-label text-code-label text-[12px]">
            <span class="text-[#4ade80]">+${totalAdditions}</span>
            <span class="text-error ml-1">-${totalDeletions}</span>
          </div>
        </div>
      </div>
      <div class="flex items-center gap-2 flex-shrink-0">
        <button type="button" class="change-undo inline-flex items-center gap-1 px-2 py-1 rounded-md text-[12px] text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high">
          <span>${live ? "Undo" : "Undo"}</span>
          <span class="material-symbols-outlined text-[14px]">undo</span>
        </button>
        <button type="button" class="change-review px-3 py-1.5 rounded-lg border border-outline-variant bg-surface-container-high text-[13px] text-on-surface hover:bg-surface-variant">${live ? "Review" : "Review here"}</button>
      </div>
    </div>
    <div class="change-list border-t border-outline-variant/50"></div>
  `;
  const list = card.querySelector(".change-list");
  const hiddenCount = Math.max(0, changes.length - 3);
  changes.slice(0, 3).forEach((item) => {
    const row = document.createElement("div");
    row.className = "flex items-center justify-between gap-3 px-4 py-2.5 text-[13px] text-on-surface hover:bg-surface-container-high/60";
    row.innerHTML = `
      <span class="font-code-label truncate"></span>
      <span class="font-code-label flex-shrink-0">
        <span class="text-[#4ade80]">+${Number(item.additions ?? 0)}</span>
        <span class="text-error ml-1">-${Number(item.deletions ?? 0)}</span>
        <span class="material-symbols-outlined text-[16px] align-middle text-on-surface-variant ml-1">expand_more</span>
      </span>
    `;
    row.querySelector(".truncate").textContent = displayPath(item.path);
    row.title = text(item.path);
    list.append(row);
  });
  if (hiddenCount) {
    const more = document.createElement("button");
    more.type = "button";
    more.className = "w-full flex items-center gap-1 px-4 py-2.5 text-[13px] text-on-surface hover:bg-surface-container-high border-t border-outline-variant/40";
    more.innerHTML = `Show ${hiddenCount} more ${hiddenCount === 1 ? "file" : "files"} <span class="material-symbols-outlined text-[16px]">expand_more</span>`;
    more.addEventListener("click", () => {
      const expanded = more.dataset.expanded === "true";
      more.dataset.expanded = String(!expanded);
      Array.from(list.querySelectorAll("[data-extra-change]")).forEach((node) => node.remove());
      if (!expanded) {
        changes.slice(3).forEach((item) => {
          const row = document.createElement("div");
          row.dataset.extraChange = "true";
          row.className = "flex items-center justify-between gap-3 px-4 py-2.5 text-[13px] text-on-surface hover:bg-surface-container-high/60";
          row.innerHTML = `<span class="font-code-label truncate"></span><span class="font-code-label flex-shrink-0"><span class="text-[#4ade80]">+${Number(item.additions ?? 0)}</span><span class="text-error ml-1">-${Number(item.deletions ?? 0)}</span></span>`;
          row.querySelector(".truncate").textContent = displayPath(item.path);
          list.append(row);
        });
        more.innerHTML = `Hide extra files <span class="material-symbols-outlined text-[16px]">expand_less</span>`;
      } else {
        more.innerHTML = `Show ${hiddenCount} more ${hiddenCount === 1 ? "file" : "files"} <span class="material-symbols-outlined text-[16px]">expand_more</span>`;
      }
    });
    card.append(more);
  }
  card.querySelector(".change-undo").addEventListener("click", (event) => undoLastChange(event.currentTarget));
  card.querySelector(".change-review").addEventListener("click", () => {
    dom.processOutput?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    dom.processOutput?.classList.add("ring-1", "ring-primary/60");
    setTimeout(() => dom.processOutput?.classList.remove("ring-1", "ring-primary/60"), 1200);
  });
  return card;
}

function updateLiveChangeSummary() {
  const holder = document.getElementById("live-change-summary");
  if (!holder) return;
  holder.innerHTML = "";
  const card = renderChangeSummaryCard(changesFromTrace(activeChat()?.trace ?? []), { live: true });
  if (card) holder.append(card);
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
        </div>
        <div class="text-on-surface font-body-md text-body-md leading-relaxed space-y-4 w-full message-content">
          <p class="whitespace-pre-wrap"></p>
        </div>
      </div>`;
  }
  if (role === "user") {
    wrap.querySelector("p").textContent = text(message.content);
  } else {
    const content = wrap.querySelector(".message-content");
    content.innerHTML = "";
    content.append(renderMarkdown(message.content));
  }
  if (role === "user" && Array.isArray(message.attachments) && message.attachments.length) {
    const chips = document.createElement("div");
    chips.className = "flex flex-wrap justify-end gap-1.5 mt-2";
    chips.innerHTML = message.attachments.map((item) => `
      <span class="inline-flex items-center gap-1 rounded-md border border-outline-variant bg-surface-container-low px-2 py-1 text-[11px] text-on-surface-variant" title="${text(item.filename)}">
        <span class="material-symbols-outlined text-[13px]">attach_file</span>${text(item.filename)}
      </span>
    `).join("");
    wrap.querySelector(".flex.flex-col.items-end")?.append(chips);
  }
  if (role === "assistant") {
    const changeCard = renderChangeSummaryCard(normalizeChanges(message));
    if (changeCard) wrap.querySelector(".message-content").appendChild(changeCard);
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
        <div id="live-change-summary" class="w-full"></div>
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

function renderSkills() {
  // Sidebar always shows all skills
  dom.sidebarSkills.innerHTML = "";
  state.skills.forEach((skill) => {
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
      toggleSkills(false);
    });
    li.append(link);
    dom.sidebarSkills.append(li);
  });

  // Dropdown shows filtered skills with keyboard navigation support
  const menuList = dom.skillsDropdown.querySelector("ul");
  menuList.innerHTML = "";
  state.filteredSkills.forEach((skill, index) => {
    const button = document.createElement("button");
    const isSelected = index === state.selectedSkillIndex;
    button.className = `w-full flex items-center gap-3 px-3 py-2.5 text-left text-body-sm text-on-surface transition-colors group focus:bg-primary/10 ${isSelected ? "bg-primary/10 border-l-2 border-primary" : "hover:bg-surface-variant"}`;
    button.type = "button";
    button.innerHTML = `
      <div class="w-7 h-7 rounded bg-primary/10 border border-primary/20 flex items-center justify-center flex-shrink-0 group-hover:border-primary/50 ${isSelected ? "border-primary/50" : ""}"></div>
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
    if (isSelected) {
      button.scrollIntoView({ block: "nearest" });
    }
    menuList.append(button);
  });
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
    if (tool === "install_package") {
      return `install - ${args.package ?? ""} (${obs?.installed ? "installed" : obs?.requiresElevation ? "elevation required" : "failed"})`;
    }
    if (tool === "database_query") {
      return `database query - ${obs?.rowCount ?? "?"} rows`;
    }
    if (tool === "http_request") {
      return `http ${args.method ?? "GET"} - ${obs?.statusCode ?? "?"} ${args.url ?? ""}`;
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
  renderAttachmentChips();
  renderMessages();
  renderPlan();
  renderLogs();
  applyPlanningVisibility();
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

function toggleSidebarSkills(force) {
  state.sidebarSkillsOpen = force ?? !state.sidebarSkillsOpen;
  dom.sidebarSkills?.classList.toggle("hidden", !state.sidebarSkillsOpen);
  if (dom.sidebarSkillsIcon) {
    dom.sidebarSkillsIcon.style.transform = state.sidebarSkillsOpen ? "rotate(180deg)" : "";
  }
}

function renderAttachmentChips() {
  if (!dom.attachmentChips) return;
  dom.attachmentChips.innerHTML = "";
  dom.attachmentChips.classList.toggle("hidden", state.pendingAttachments.length === 0);
  for (const item of state.pendingAttachments) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "inline-flex items-center gap-1.5 rounded-lg border border-outline-variant bg-surface-container-low px-2.5 py-1.5 text-[12px] text-on-surface-variant hover:text-on-surface";
    chip.title = `Remove ${item.filename}`;
    chip.innerHTML = `<span class="material-symbols-outlined text-[15px]">attach_file</span><span class="max-w-[180px] truncate"></span><span class="material-symbols-outlined text-[14px]">close</span>`;
    chip.querySelector(".truncate").textContent = item.filename;
    chip.addEventListener("click", () => {
      state.pendingAttachments = state.pendingAttachments.filter((attachment) => attachment.id !== item.id);
      renderAttachmentChips();
    });
    dom.attachmentChips.append(chip);
  }
}

function historyForRequest(chat) {
  return (chat.messages ?? []).slice(0, -1).map((message) => {
    const { attachments, ...rest } = message;
    return rest;
  });
}

function applyPlanningVisibility() {
  const planSection = dom.executionPlan?.closest(".p-6");
  if (planSection) planSection.classList.toggle("hidden", !state.planningMode);
  dom.planningToggle?.classList.toggle("border-primary", state.planningMode);
  dom.planningToggle?.classList.toggle("text-primary", state.planningMode);
  dom.planningToggle?.setAttribute("aria-pressed", String(state.planningMode));
}

function updateSkillMenuFromInput() {
  const value = dom.composer.value.trimStart();
  if (value.startsWith("/") && !value.includes(" ")) {
    const query = value.slice(1).toLowerCase();
    state.filteredSkills = state.skills.filter((skill) =>
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
  state.bootstrap = await response.json();
  state.projects = state.bootstrap.projects ?? [];
  state.skills = state.bootstrap.skills ?? [];
  state.filteredSkills = state.skills;
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
  toggleSidebarSkills(false);
  applyPlanningVisibility();
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

async function registerSelectedProject(path) {
  const normalizedPath = text(path).replace(/[\\/]+$/, "");
  const name = normalizedPath.split(/[\\/]/).pop() || `Project ${state.projects.length + 1}`;
  const response = await fetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, rootPath: path })
  });
  const data = await response.json();
  state.projects.unshift(data.project);
  state.chats = [data.chat, ...state.chats];
  state.activeProjectId = data.project.id;
  state.activeChatId = data.chat.id;
  data.chat.messages = [{ role: "assistant", content: state.bootstrap.app.welcome }];
  renderAll();
}

async function selectProjectFolder(mode) {
  const res = await fetch("/api/select-folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, startPath: activeProject()?.rootPath || state.bootstrap?.projectRoot })
  });
  const data = await res.json();
  if (data.cancelled || !data.path) return;
  await registerSelectedProject(data.path);
}

async function createProject() {
  await selectProjectFolder("create");
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
    body: JSON.stringify({ query, projectId: state.activeProjectId })
  });
  const data = await response.json();
  if (data.projects?.length) state.projects = data.projects;
  state.chats = data.chats ?? state.chats;
  if (data.skills?.length) state.skills = data.skills;
  renderProjects();
  renderSkills();
}

async function uploadFiles(files) {
  for (const file of files) {
    const body = new FormData();
    body.append("file", file);
    if (state.activeProjectId) body.append("projectId", state.activeProjectId);
    const response = await fetch("/api/files/upload", { method: "POST", body });
    const data = await response.json();
    if (data.upload) state.pendingAttachments.push(data.upload);
  }
  renderAttachmentChips();
  dom.fileInput.value = "";
}

function applyEvent(event) {
  const chat = activeChat();
  if (event.autoPlan) state.planningMode = true;
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
  applyPlanningVisibility();
  updateLiveChangeSummary();

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
  const promptAttachments = [...state.pendingAttachments];
  chat.messages.push({ role: "user", content: task, attachments: promptAttachments });
  chat.plan = [];
  chat.trace = [];
  dom.composer.value = "";
  state.pendingAttachments = [];
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
        history: historyForRequest(chat),
        attachments: promptAttachments,
        projectRoot: activeProject()?.rootPath,
        projectId: state.activeProjectId,
        chatId: state.activeChatId,
        planningMode: state.planningMode,
        permissionMode: state.permissionMode
      })
    });
    const result = await readStream(response);
    const changes = result?.changes?.length ? result.changes : changesFromTrace(chat.trace);
    chat.messages.push({ role: "assistant", content: result?.final ?? "Agent finished without a final response.", files: result?.files ?? changes.map((item) => item.path), changes });
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
  dom.settingsModal.classList.remove("hidden");
  refreshBrowserSession();
  const connected = Array.from(dom.settingsModal.querySelectorAll("span")).find((span) => span.textContent.includes("CONNECTED") || span.textContent.includes("OFFLINE") || span.textContent.includes("ollama"));
  try {
    const models = await (await fetch("/api/models")).json();
    document.querySelector("#current-model-name").textContent = models.model ?? "local";
    if (connected) connected.textContent = models.error ? "OFFLINE" : `${models.provider}: ${models.model}`;
  } catch (_error) {
    if (connected) connected.textContent = "OFFLINE";
  }
}

async function refreshBrowserSession() {
  if (!dom.browserSessionBadge || !dom.browserSessionMessage) return;
  try {
    const data = await (await fetch("/api/browser-session")).json();
    dom.browserSessionBadge.textContent = data.active ? "ACTIVE" : "OFF";
    dom.browserSessionBadge.className = data.active
      ? "px-2 py-0.5 rounded-full bg-primary/20 text-primary text-[10px] font-bold"
      : "px-2 py-0.5 rounded-full bg-surface-variant text-on-surface-variant text-[10px] font-bold";
    dom.browserSessionMessage.textContent = data.message ?? "No authenticated browser session is active.";
  } catch (error) {
    dom.browserSessionMessage.textContent = `Browser status unavailable: ${error.message}`;
  }
}

async function startBrowserSession() {
  const data = await (await fetch("/api/browser-session/start", { method: "POST" })).json();
  await refreshBrowserSession();
  if (dom.browserSessionMessage && (data.blocked || data.error)) {
    dom.browserSessionMessage.textContent = data.message ?? data.error;
  }
}

async function closeBrowserSession() {
  await fetch("/api/browser-session/close", { method: "POST" });
  await refreshBrowserSession();
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
  await selectProjectFolder("open");
});
dom.newChat?.addEventListener("click", (event) => {
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
dom.browserSessionStart?.addEventListener("click", startBrowserSession);
dom.browserSessionClose?.addEventListener("click", closeBrowserSession);
dom.sidebarSkillsToggle?.addEventListener("click", () => toggleSidebarSkills());
dom.composer.addEventListener("input", updateSkillMenuFromInput);
dom.composer.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    toggleSkills(false);
    state.selectedSkillIndex = -1;
    renderSkills();
  }

  const isDropdownVisible = !dom.skillsDropdown.classList.contains("hidden");
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
        dom.composer.value = `${skill.trigger || `/${skill.name}`} `;
        toggleSkills(false);
        state.selectedSkillIndex = -1;
        return;
      }
    }
  }

  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendTask();
  }
});
dom.planningToggle.addEventListener("click", () => {
  state.planningMode = !state.planningMode;
  applyPlanningVisibility();
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
    state.permissionMode = e.currentTarget.dataset.permissionMode === "safe" ? "safe" : "full";
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
