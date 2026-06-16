const state = {
  config: null,
  memory: null,
  semantic: null,
  activeProfileId: null,
  view: "overview",
  chats: [],
  selectedChat: null,
  memoryChat: "",
  chatSummary: null,
  chatTypes: [],
  lastMessages: [],
  suite: null,
  semanticRuns: null,
  autoReply: null,
  skills: { skills: [], runs: [], stats: {} },
  selectedSkillId: "",
  skillConfigDirty: false,
  debug: null,
  preview: null,
  lastOutbox: null,
  memoryUi: {
    tab: "people",
    selectedPersonId: null,
    selectedFactId: null,
    selectedFocusId: null,
  },
  graph: {
    filter: "all",
    selectedId: null,
    nodes: [],
    edges: [],
    positions: new Map(),
    transformFrame: 0,
    scale: 1,
    x: 0,
    y: 0,
    worldWidth: 1800,
    worldHeight: 1120,
    dragging: false,
    dragMoved: false,
    dragStartX: 0,
    dragStartY: 0,
    lastX: 0,
    lastY: 0,
  },
};

const $ = (id) => document.getElementById(id);

const pageMeta = {
  overview: ["群记忆总览", "查看服务运行、聊天同步、长期记忆和知识图谱。"],
  chat: ["聊天记录", "在 8078 内查看会话、消息、图片、表情、引用和搜索。"],
  services: ["服务状态", "在 8078 内查看容器、端口、同步和索引健康。"],
  models: ["模型配置", "新增、保存、检测和选择 OpenAI-compatible 模型。"],
  persona: ["人格设置", "Agent 性格、安全边界和自动回复判定开关。"],
  talk: ["接话策略", "四种接话模式、阈值、随机发送延迟和评分标准。"],
  skills: ["技能中心", "导入、安装、启停、测试和导出 SKILL.md / OpenAPI / 内置技能。"],
  memory: ["群记忆中枢", "人物画像、长期事实、群故事线和聚焦关系都来自 AI 记忆库。"],
  test: ["模型测试", "向当前活跃模型发送一次短测试。"],
};

const layerNames = {
  message_vector: "消息级检索",
  long_term_facts: "长期事实总结",
  people_profiles: "人物偏好",
  group_summaries: "群聊摘要",
  knowledge_graph: "知识图谱",
  fact_review: "自动事实",
};

const modeNames = {
  quiet: "安静",
  normal: "正常",
  active: "活跃",
  wild: "发疯",
};

const modeDescriptions = {
  quiet: "只在明确 @、强求助或重要问题时接话。",
  normal: "日常群聊推荐，问题和求回应会积极接。",
  active: "更愿意接梗、补充信息和承接冷场。",
  wild: "很主动，适合测试和希望热闹的小群。",
};

const WX_EMOJI = {
  微笑: "😊", 撇嘴: "😣", 色: "😍", 发呆: "😳", 得意: "😎", 流泪: "😢", 害羞: "😊", 闭嘴: "🤐",
  睡: "😴", 大哭: "😭", 尴尬: "😅", 发怒: "😡", 调皮: "😜", 呲牙: "😁", 惊讶: "😮", 难过: "😞",
  酷: "😎", 冷汗: "😰", 抓狂: "😫", 吐: "🤮", 偷笑: "🤭", 可爱: "☺️", 白眼: "🙄", 傲慢: "😤",
  饥饿: "🤤", 困: "😪", 惊恐: "😨", 流汗: "😓", 憨笑: "😄", 大兵: "🫡", 奋斗: "💪", 咒骂: "🤬",
  疑问: "❓", 嘘: "🤫", 晕: "😵", 折磨: "😩", 衰: "😥", 骷髅: "💀", 敲打: "🔨", 再见: "👋",
  擦汗: "😓", 抠鼻: "🤏", 鼓掌: "👏", 糗大了: "😳", 坏笑: "😏", 左哼哼: "😤", 右哼哼: "😤",
  哈欠: "🥱", 鄙视: "😒", 委屈: "🥺", 快哭了: "🥺", 阴险: "😈", 亲亲: "😘", 吓: "😱", 可怜: "🥺",
  菜刀: "🔪", 西瓜: "🍉", 啤酒: "🍺", 篮球: "🏀", 乒乓: "🏓", 咖啡: "☕", 饭: "🍚", 猪头: "🐷",
  玫瑰: "🌹", 凋谢: "🥀", 示爱: "💗", 爱心: "❤️", 心碎: "💔", 蛋糕: "🎂", 闪电: "⚡", 炸弹: "💣",
  刀: "🔪", 足球: "⚽", 瓢虫: "🐞", 便便: "💩", 月亮: "🌙", 太阳: "☀️", 礼物: "🎁", 拥抱: "🤗",
  强: "👍", 弱: "👎", 握手: "🤝", 胜利: "✌️", 抱拳: "🙏", 勾引: "👆", 拳头: "✊", 差劲: "👎",
  爱你: "🤟", NO: "🙅", OK: "👌", 爱情: "💑", 飞吻: "😘", 跳跳: "💃", 发抖: "🥶", 怄火: "😤",
  转圈: "💫", 磕头: "🙇", 回头: "↩️", 跳绳: "🏃", 挥手: "👋", 激动: "🤩", 街舞: "💃", 献吻: "😘",
  左太极: "☯️", 右太极: "☯️", 嘿哈: "😆", 捂脸: "🤦", 奸笑: "😏", 机智: "🤓", 皱眉: "😟",
  耶: "✌️", 红包: "🧧", 鸡: "🐔", Emm: "🤔", 加油: "💪", 汗: "😓", 天啊: "😱", 社会社会: "🤙",
  旺柴: "🐶", 好的: "👌", 打脸: "🤦", 哇: "😲", 翻白眼: "🙄", 666: "👍", 让我看看: "👀",
  叹气: "😮‍💨", 苦涩: "😣", 裂开: "💔", 嘴唇: "💋", 破涕为笑: "😂", 脸红: "☺️"
};

function fmtNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toLocaleString("zh-CN");
}

function fmtTime(value) {
  if (!value) return "";
  const ts = Number(value);
  if (!Number.isFinite(ts)) return String(value);
  return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
}

function fmtAge(seconds) {
  if (seconds === null || seconds === undefined) return "--";
  const value = Number(seconds);
  if (!Number.isFinite(value)) return "--";
  if (value < 60) return `${Math.round(value)} 秒前`;
  if (value < 3600) return `${Math.round(value / 60)} 分钟前`;
  return `${Math.round(value / 3600)} 小时前`;
}

function fmtDuration(ms) {
  const value = Number(ms);
  if (!Number.isFinite(value) || value <= 0) return "";
  if (value < 1000) return `${Math.round(value)}ms`;
  return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)}s`;
}

function fmtIsoTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || JSON.stringify(payload));
  return payload;
}

function activeProfile() {
  const profiles = state.config?.llm_profiles || [];
  return profiles.find((item) => item.id === state.activeProfileId) || profiles[0] || {};
}

function activeMode() {
  const agent = state.config?.agent || {};
  return (state.config?.talk_modes || {})[agent.reply_mode] || {};
}

function statusUrl() {
  const params = new URLSearchParams();
  if (state.memoryChat) params.set("chat", state.memoryChat);
  const query = params.toString();
  return `/api/status${query ? `?${query}` : ""}`;
}

function activeMemoryChat() {
  return state.chats.find((chat) => chat.username === state.memoryChat) || null;
}

function resetMemorySelection() {
  state.graph.selectedId = null;
  state.graph.didFit = false;
  state.memoryUi.selectedPersonId = null;
  state.memoryUi.selectedFactId = null;
  state.memoryUi.selectedFocusId = null;
}

function updateTop() {
  const config = state.config || {};
  const agent = config.agent || {};
  const profile = activeProfile();
  const mode = activeMode();
  const health = profile.health || {};
  const memory = state.memory || {};
  const semantic = state.semantic || {};
  const totals = semantic.totals || {};
  const scopedObjects =
    Number(totals.facts || 0) +
    Number(totals.people || 0) +
    Number(totals.summaries || 0) +
    Number(totals.edges || 0);
  const memoryObjects =
    Number(memory.facts || 0) +
    Number(memory.people_profiles || 0) +
    Number(memory.group_summaries || 0) +
    Number(memory.graph_edges || 0);

  $("agentState").textContent = agent.auto_reply_enabled ? "自动接话判定已开启" : "自动回复未启用";
  $("memoryBadge").textContent = `${fmtNumber(memory.ai_indexed_messages)} / ${fmtNumber(memory.messages)}`;
  $("syncHint").textContent = `${fmtNumber(memory.chats)} 会话`;
  updateServiceStat();
  $("memoryObjectCount").textContent = fmtNumber(state.memoryChat ? scopedObjects : memoryObjects);
  $("memoryHint").textContent = state.memoryChat
    ? `${fmtNumber(totals.summaries)} 摘要 · ${fmtNumber(totals.people)} 人物 · ${fmtNumber(totals.facts)} 事实`
    : `${fmtNumber(memory.group_summaries)} 摘要 · ${fmtNumber(memory.people_profiles)} 人物 · ${fmtNumber(memory.facts)} 事实`;
  $("navChatCount").textContent = fmtNumber(memory.chats);
  $("navMemoryCount").textContent = fmtNumber(memoryObjects);
  $("navModelCount").textContent = fmtNumber((config.llm_profiles || []).length);
  if ($("navSkillCount")) $("navSkillCount").textContent = fmtNumber(state.skills?.stats?.enabled ?? state.skills?.skills?.length ?? 0);

  if (health.ok) {
    $("modelHealth").textContent = "连通";
    $("modelHealth").className = "ok";
    $("modelHint").textContent = `${profile.model || "--"} · ${health.elapsed_ms || "--"} ms`;
    $("llmSummary").textContent = `${profile.model || "--"} · 连通`;
  } else if (health.error) {
    $("modelHealth").textContent = "异常";
    $("modelHealth").className = "bad";
    $("modelHint").textContent = formatHealthError(health.error);
    $("llmSummary").textContent = `${profile.model || "--"} · 异常`;
  } else {
    $("modelHealth").textContent = "待检测";
    $("modelHealth").className = "";
    $("modelHint").textContent = "等待检测";
    $("llmSummary").textContent = "等待模型检测";
  }

  renderModeCards();
  renderOverviewServices();
  renderOverviewMemory();
  renderGraph(semantic.graph || { nodes: [], edges: [] });
  renderAutoReplyLive();
}

function serviceCounts() {
  const services = state.suite?.services || [];
  const bad = services.filter((service) => {
    const containerAvailable = service.container?.available !== false;
    return !(service.health?.ok && (!containerAvailable || service.container?.ok));
  });
  return { total: services.length, bad: bad.length, ok: services.length - bad.length, badServices: bad };
}

function updateServiceStat() {
  const counts = serviceCounts();
  if (!counts.total) {
    $("runMode").textContent = "--";
    $("talkHint").textContent = "等待服务状态";
    return;
  }
  $("runMode").textContent = `${counts.ok}/${counts.total}`;
  $("talkHint").textContent = counts.bad ? `${counts.bad} 个异常` : "全部正常";
}

function formatHealthError(error) {
  if (!error) return "未知错误";
  const text = typeof error === "string" ? error : JSON.stringify(error);
  return text.length > 42 ? `${text.slice(0, 42)}...` : text;
}

function healthClass(health) {
  if (!health || health.ok !== true) return health?.stale ? "warn" : "bad";
  return "ok";
}

function healthText(health) {
  if (!health) return "未知";
  if (health.ok === true) return "正常";
  if (health.stale) return "延迟";
  return "异常";
}

function containerClass(container) {
  if (!container || container.available === false) return "bad";
  if (container.ok === true) return "ok";
  if (container.restarting || container.paused) return "warn";
  return "bad";
}

function containerText(container) {
  if (!container || container.available === false) return "未找到";
  if (container.ok === true) return "running";
  if (container.restarting) return "restarting";
  if (container.paused) return "paused";
  return container.status || "异常";
}

function compactJson(value) {
  if (!value) return "{}";
  const copy = JSON.parse(JSON.stringify(value));
  delete copy.refresh?.skipped;
  if (copy.details_json && typeof copy.details_json === "string") {
    try {
      copy.details = JSON.parse(copy.details_json);
      delete copy.details_json;
    } catch {
      // keep original field
    }
  }
  return JSON.stringify(copy, null, 2);
}

function switchView(view) {
  state.view = pageMeta[view] ? view : "overview";
  document.querySelectorAll(".page").forEach((page) => page.classList.toggle("active", page.dataset.page === state.view));
  document.querySelectorAll(".nav button").forEach((item) => item.classList.toggle("active", item.dataset.view === state.view));
  const [title, subtitle] = pageMeta[state.view];
  $("pageTitle").textContent = title;
  $("pageSubtitle").textContent = subtitle;
  if (state.view === "chat" && !state.chats.length) loadChats();
  if (state.view === "services") loadSuiteStatus();
  if (state.view === "skills") loadSkills().catch((error) => console.warn(error));
  if (state.view === "overview") setTimeout(fitGraph, 0);
}

function mergeRuntimeStatus(payload) {
  const incomingProfiles = payload.config?.llm_profiles || [];
  const healthById = Object.fromEntries(incomingProfiles.map((profile) => [profile.id, profile.health || {}]));
  for (const profile of state.config?.llm_profiles || []) {
    if (healthById[profile.id]) profile.health = healthById[profile.id];
  }
  state.memory = payload.memory;
  state.semantic = payload.semantic_memory;
  state.semanticRuns = payload.semantic_runs || state.semanticRuns;
  state.autoReply = payload.auto_reply || state.autoReply;
  renderAutoReplyStatus();
  renderMemoryChatSelects();
}

async function setMemoryChat(username, options = {}) {
  const next = String(username || "").trim();
  if (state.memoryChat === next && !options.force) {
    renderMemoryChatSelects();
    return;
  }
  state.memoryChat = next;
  resetMemorySelection();
  renderMemoryChatSelects();
  if (options.fetch !== false) {
    await refreshStatus();
  }
}

function fillProfileForm(profile) {
  $("llmName").value = profile.name || "";
  $("baseUrl").value = profile.base_url || "";
  $("model").value = profile.model || "";
  $("apiKey").value = "";
  $("temperature").value = profile.temperature ?? 0.4;
  $("contextWindow").value = profile.context_window ?? 1000000;
  $("maxTokens").value = profile.max_tokens ?? 512;
  $("healthInterval").value = profile.health_check_interval_seconds ?? 120;
  $("healthEnabled").checked = Boolean(profile.health_check_enabled);
  $("keyState").className = profile.api_key_configured ? "pill ok" : "pill bad";
  $("keyState").textContent = profile.api_key_configured ? `Key 已配置 · ${profile.api_key_tail}` : "Key 未配置";
}

function syncProfileFromForm() {
  if (!state.config) return;
  const profile = activeProfile();
  if (!profile.id) return;
  profile.name = $("llmName").value.trim();
  profile.base_url = $("baseUrl").value.trim();
  profile.model = $("model").value.trim();
  const key = $("apiKey").value.trim();
  if (key) profile.api_key = key;
  profile.temperature = Number($("temperature").value || 0.4);
  profile.context_window = Number($("contextWindow").value || 1000000);
  profile.max_tokens = Number($("maxTokens").value || 512);
  profile.health_check_interval_seconds = Number($("healthInterval").value || 120);
  profile.health_check_enabled = $("healthEnabled").checked;
}

function setActiveProfile(id) {
  syncProfileFromForm();
  state.activeProfileId = id;
  state.config.active_llm_profile_id = id;
  renderProfiles();
  fillProfileForm(activeProfile());
  updateTop();
}

function renderProfiles() {
  const root = $("profileTabs");
  root.innerHTML = "";
  for (const profile of state.config.llm_profiles || []) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `profile-tab ${profile.id === state.activeProfileId ? "active" : ""}`;
    button.innerHTML = `<span>${escapeHtml(profile.name || profile.id)}</span><small>${profile.health?.ok ? "连通" : "未检"}</small>`;
    button.addEventListener("click", () => setActiveProfile(profile.id));
    root.appendChild(button);
  }
}

function fillAgent() {
  const config = state.config;
  const agent = config.agent || {};
  $("agentEnabled").checked = Boolean(agent.enabled);
  $("autoReplyEnabled").checked = Boolean(agent.auto_reply_enabled);
  if ($("agentAliases")) $("agentAliases").value = (agent.aliases || []).join("\n");
  $("personality").value = agent.personality || "";
  $("safetyPolicy").value = agent.safety_policy || "";
  const select = $("replyMode");
  select.innerHTML = "";
  for (const [key, mode] of Object.entries(config.talk_modes || {})) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = `${mode.label} · 阈值 ${mode.threshold}`;
    select.appendChild(option);
  }
  select.value = agent.reply_mode || "normal";
  renderTalkModePicker();
  renderDebugModeOptions();
}

function syncAgentFromForm() {
  state.config.agent = {
    ...(state.config.agent || {}),
    enabled: $("agentEnabled").checked,
    auto_reply_enabled: $("autoReplyEnabled").checked,
    reply_mode: $("replyMode").value,
    aliases: $("agentAliases") ? $("agentAliases").value.split(/\n|,/).map((item) => item.trim()).filter(Boolean) : state.config.agent?.aliases || [],
    personality: $("personality").value,
    safety_policy: $("safetyPolicy").value,
  };
}

function renderModeCards() {
  const root = $("modeCards");
  if (!state.config || !root) return;
  const active = state.config.agent?.reply_mode || "normal";
  root.innerHTML = "";
  for (const [key, mode] of Object.entries(state.config.talk_modes || {})) {
    const row = document.createElement("div");
    row.className = `mode ${key === active ? "active" : ""}`;
    row.innerHTML = `<strong>${escapeHtml(mode.label || modeNames[key] || key)}</strong><div class="meter"><span style="width:${Number(mode.threshold || 0)}%"></span></div><em>${mode.threshold}</em>`;
    root.appendChild(row);
  }
}

async function setReplyMode(key) {
  if (!state.config?.talk_modes?.[key]) return;
  syncTalkFromForm();
  state.config.agent = { ...(state.config.agent || {}), reply_mode: key };
  const select = $("replyMode");
  if (select) select.value = key;
  renderTalkModePicker();
  renderTalkModes();
  updateTop();
  const activeButton = document.querySelector(`.talk-mode-card[data-mode="${CSS.escape(key)}"]`);
  if (activeButton) {
    activeButton.classList.add("saving");
    activeButton.setAttribute("aria-busy", "true");
  }
  try {
    const payload = await fetchJson("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectConfig()),
    });
    state.config = payload.config;
    state.activeProfileId = payload.config.active_llm_profile_id;
    fillAgent();
    renderTalkModes();
    updateTop();
  } catch (error) {
    console.warn("模式保存失败", error);
    const saveButton = $("saveTalkBtn");
    if (saveButton) saveButton.textContent = "模式保存失败";
  } finally {
    if (activeButton) {
      activeButton.classList.remove("saving");
      activeButton.removeAttribute("aria-busy");
    }
  }
}

function renderTalkModePicker() {
  const root = $("talkModePicker");
  if (!state.config || !root) return;
  const active = state.config.agent?.reply_mode || "normal";
  root.innerHTML = "";
  for (const [key, mode] of Object.entries(state.config.talk_modes || {})) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `talk-mode-card ${key === active ? "active" : ""}`;
    button.dataset.mode = key;
    button.innerHTML = `
      <span class="mode-title">${escapeHtml(mode.label || modeNames[key] || key)}</span>
      <strong>${escapeHtml(mode.threshold)}</strong>
      <span>${escapeHtml(modeDescriptions[key] || "自定义接话策略")}</span>
      <em>间隔 ${escapeHtml(mode.min_interval_seconds ?? 0)}s · 每小时 ${escapeHtml(mode.hourly_limit ?? 0)} · 连续 ${escapeHtml(mode.streak_limit ?? 0)}</em>
    `;
    button.addEventListener("click", () => setReplyMode(key));
    root.appendChild(button);
  }
}

function renderDebugModeOptions() {
  const select = $("debugMode");
  if (!select || !state.config) return;
  const current = select.value || state.config.agent?.reply_mode || "normal";
  select.innerHTML = "";
  for (const [key, mode] of Object.entries(state.config.talk_modes || {})) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = `${mode.label || modeNames[key] || key} · 阈值 ${mode.threshold}`;
    select.appendChild(option);
  }
  select.value = current;
}

function renderTalkModes() {
  $("freeTaskTtl").value = state.config.talk_scoring?.free_task_ttl_seconds ?? 120;
  const root = $("talkModes");
  root.innerHTML = "";
  const active = state.config.agent?.reply_mode || "normal";
  for (const [key, mode] of Object.entries(state.config.talk_modes || {})) {
    const row = document.createElement("div");
    row.className = `talk-mode-row ${key === active ? "active" : ""}`;
    row.innerHTML = `
      <strong>${escapeHtml(mode.label)}</strong>
      <label><span>接话阈值</span><input data-mode="${key}" data-field="threshold" type="number" min="0" max="100" value="${mode.threshold}"></label>
      <label><span>最小间隔</span><input data-mode="${key}" data-field="min_interval_seconds" type="number" min="0" value="${mode.min_interval_seconds}"></label>
      <label><span>每小时上限</span><input data-mode="${key}" data-field="hourly_limit" type="number" min="0" value="${mode.hourly_limit}"></label>
      <label><span>连续上限</span><input data-mode="${key}" data-field="streak_limit" type="number" min="0" value="${mode.streak_limit}"></label>`;
    root.appendChild(row);
  }
  root.querySelectorAll("[data-mode][data-field]").forEach((input) => {
    input.addEventListener("input", markTalkSettingsDirty);
  });
  if ($("freeTaskTtl")) $("freeTaskTtl").oninput = markTalkSettingsDirty;
  renderScores();
}

function syncTalkFromForm() {
  for (const input of document.querySelectorAll("[data-mode][data-field]")) {
    const mode = input.getAttribute("data-mode");
    const field = input.getAttribute("data-field");
    state.config.talk_modes[mode][field] = Number(input.value || 0);
  }
  const select = $("replyMode");
  if (select) state.config.agent.reply_mode = select.value || state.config.agent.reply_mode || "normal";
  state.config.talk_scoring.free_task_ttl_seconds = Number($("freeTaskTtl").value || 0);
  renderTalkModePicker();
}

function markTalkSettingsDirty() {
  if (!state.config) return;
  syncTalkFromForm();
  renderDebugModeOptions();
  renderModeCards();
  updateTop();
  const button = $("saveTalkBtn");
  if (button && !button.disabled) button.textContent = "保存并立即生效";
}

function fillReplySenderForm() {
  const sender = state.config?.reply_sender || {};
  if (!$("replySenderEnabled")) return;
  $("replySenderEnabled").checked = Boolean(sender.enabled);
  $("replySenderMode").value = sender.mode || "draft_only";
  $("replyPollInterval").value = sender.poll_interval_seconds ?? 5;
  $("replyMaxPerCycle").value = sender.max_messages_per_cycle ?? 8;
  $("switchDelayMin").value = sender.switch_delay_min_seconds ?? 1;
  $("switchDelayMax").value = sender.switch_delay_max_seconds ?? 2.2;
  $("sendDelayMin").value = sender.send_delay_min_seconds ?? 1.2;
  $("sendDelayMax").value = sender.send_delay_max_seconds ?? 4.8;
  renderReplyAllowedChats();
}

function renderReplyAllowedChats() {
  const select = $("replyAllowedChats");
  if (!select || !state.config) return;
  const selected = new Set(state.config.reply_sender?.allowed_chats || []);
  const groupChats = (state.chats || []).filter((chat) => String(chat.username || "").includes("@chatroom") || chat.is_group);
  select.innerHTML = groupChats.map((chat) => {
    const label = chat.display_name || chat.username;
    return `<option value="${escapeAttr(chat.username)}" ${selected.has(chat.username) || selected.has(label) ? "selected" : ""}>${escapeHtml(label)}</option>`;
  }).join("");
  if (!select.innerHTML) {
    select.innerHTML = `<option value="" disabled>等待同步群聊列表</option>`;
  }
}

function syncReplySenderFromForm() {
  if (!$("replySenderEnabled") || !state.config) return;
  const selected = Array.from($("replyAllowedChats").selectedOptions || [])
    .map((option) => option.value)
    .filter(Boolean);
  state.config.reply_sender = {
    ...(state.config.reply_sender || {}),
    enabled: $("replySenderEnabled").checked,
    mode: $("replySenderMode").value || "draft_only",
    allowed_chats: selected,
    send_to_active_chat_only: false,
    require_manual_approval: $("replySenderMode").value !== "auto_send",
    poll_interval_seconds: Number($("replyPollInterval").value || 5),
    max_messages_per_cycle: Number($("replyMaxPerCycle").value || 8),
    retry_failed_attempts: Number(state.config.reply_sender?.retry_failed_attempts ?? 2),
    min_interval_seconds: Number(state.config.reply_sender?.min_interval_seconds ?? 0),
    hourly_limit: Number(state.config.reply_sender?.hourly_limit ?? 0),
    streak_limit: Number(state.config.reply_sender?.streak_limit ?? 0),
    switch_delay_min_seconds: Number($("switchDelayMin").value || 0),
    switch_delay_max_seconds: Number($("switchDelayMax").value || 0),
    send_delay_min_seconds: Number($("sendDelayMin").value || 0),
    send_delay_max_seconds: Number($("sendDelayMax").value || 0),
  };
}

function renderAutoReplyStatus() {
  const root = $("autoReplyStatus");
  if (!root) return;
  const auto = state.autoReply || {};
  const active = Boolean(auto.active);
  const statusClass = active ? "ok" : auto.ok === false ? "bad" : "warn";
  const statusText = active ? "自动发送运行中" : auto.ok === false ? "自动发送异常" : "自动发送未生效";
  const events = (auto.recent_events || []).slice(0, 4);
  const lastBits = [
    `模式 ${auto.mode || "--"}`,
    `轮询 ${fmtNumber(auto.poll_interval_seconds ?? 5)} 秒`,
    `已发 ${fmtNumber(auto.sent_count || 0)}`,
    `失败 ${fmtNumber(auto.failed_count || 0)}`,
    `跳过 ${fmtNumber(auto.skipped_count || 0)}`,
    auto.sender?.active_chat_display_name ? `当前窗口 ${auto.sender.active_chat_display_name}` : "",
    auto.last_chat_display_name ? `最近 ${auto.last_chat_display_name}` : "",
    auto.last_decision ? `判定 ${auto.last_decision} ${fmtNumber(auto.last_score || 0)}/${fmtNumber(auto.last_threshold || 0)}` : "",
    auto.last_skip_reason ? `状态 ${auto.last_skip_reason}` : "",
    auto.last_error ? `错误 ${auto.last_error}` : "",
  ].filter(Boolean);
  root.innerHTML = `
    <div class="auto-orb ${statusClass}"></div>
    <div>
      <strong>${escapeHtml(statusText)}</strong>
      <span>${escapeHtml(lastBits.join(" · "))}</span>
      <div class="auto-reply-events">
        ${events.length ? events.map((event) => `<em>${escapeHtml(event.at || "")} · ${escapeHtml(event.message || event.kind || "")}</em>`).join("") : "<em>暂无自动发送事件</em>"}
      </div>
    </div>
  `;
}

function autoLiveTone(auto, live) {
  if (auto?.ok === false || live?.phase === "failed") return "bad";
  if (!auto?.active) return "warn";
  if (["candidate", "scoring", "thinking", "ready", "sending", "confirming"].includes(live?.phase)) return "busy";
  if (live?.phase === "silent" || live?.phase === "skipped") return "warn";
  if (live?.phase === "sent") return "ok";
  return "ok";
}

function autoLivePhaseText(auto, live) {
  if (auto?.ok === false) return "自动回复异常";
  if (!auto?.active) return "自动回复未生效";
  return live?.phase_label || "自动回复运行中";
}

function renderAutoReplyLive() {
  const card = $("autoReplyLiveCard");
  if (!card) return;
  const auto = state.autoReply || {};
  const live = auto.live || {};
  const details = live.details || {};
  const tone = autoLiveTone(auto, live);
  const dot = $("autoLiveDot");
  card.classList.toggle("busy", tone === "busy");
  card.classList.toggle("ok", tone === "ok");
  card.classList.toggle("warn", tone === "warn");
  card.classList.toggle("bad", tone === "bad");
  if (dot) dot.className = `auto-orb ${tone === "busy" ? "ok busy" : tone}`;
  $("autoLivePhase").textContent = autoLivePhaseText(auto, live);
  $("autoLiveUpdated").textContent = live.updated_at ? `更新 ${fmtIsoTime(live.updated_at)}` : `轮询 ${fmtNumber(auto.poll_interval_seconds ?? 5)}s`;
  const metaBits = [
    live.chat_display_name ? `群 ${live.chat_display_name}` : "",
    live.sender_hint ? `发言人 ${live.sender_hint}` : "",
    live.decision ? `判定 ${live.decision}` : "",
    live.score || live.threshold ? `评分 ${fmtNumber(live.score || 0)}/${fmtNumber(live.threshold || 0)}` : "",
    details.llm_elapsed_ms ? `模型 ${fmtDuration(details.llm_elapsed_ms)}` : "",
    details.preview_elapsed_ms ? `生成 ${fmtDuration(details.preview_elapsed_ms)}` : "",
    details.send_elapsed_ms ? `发送 ${fmtDuration(details.send_elapsed_ms)}` : "",
    details.delays?.switch_delay_seconds ? `切群等待 ${fmtDuration(details.delays.switch_delay_seconds * 1000)}` : "",
    details.delays?.send_delay_seconds ? `发送等待 ${fmtDuration(details.delays.send_delay_seconds * 1000)}` : "",
    details.confirmed === true ? "已同步确认" : details.confirmed === false ? "未确认同步" : "",
    details.reason === "no_new_messages" ? "无新消息" : "",
    details.sender_mode ? `模式 ${details.sender_mode}` : "",
    live.error ? `错误 ${live.error}` : "",
  ].filter(Boolean);
  $("autoLiveMeta").textContent = metaBits.length ? metaBits.join(" · ") : "自动发送器正在等待新消息";
  const source = live.source_text ? `触发：${live.source_text}` : "";
  const reply = live.reply_text ? `回复：${live.reply_text}` : source || "暂无触发消息";
  $("autoLiveReply").textContent = reply;
  const events = (auto.recent_events || []).slice(0, 3);
  $("autoLiveTimeline").innerHTML = events.length
    ? events.map((event) => `<span>${escapeHtml(fmtIsoTime(event.at))} · ${escapeHtml(event.message || event.kind || "")}</span>`).join("")
    : `<span>暂无自动回复事件</span>`;
}

function replyDelayText(details) {
  const delays = details?.delays || details?.open_chat?.delays || {};
  const switchDelay = Number(delays.switch_delay_seconds ?? details?.open_chat?.switch_delay_seconds ?? 0);
  const sendDelay = Number(delays.send_delay_seconds ?? 0);
  const parts = [];
  if (Number.isFinite(switchDelay) && switchDelay > 0) parts.push(`切群等待 ${switchDelay.toFixed(2)}s`);
  if (Number.isFinite(sendDelay) && sendDelay > 0) parts.push(`发送前等待 ${sendDelay.toFixed(2)}s`);
  return parts.length ? ` · ${parts.join(" · ")}` : "";
}

function renderScores() {
  const positive = $("positiveScores");
  const negative = $("negativeScores");
  positive.innerHTML = "";
  negative.innerHTML = "";
  for (const item of state.config.talk_scoring?.positive || []) positive.appendChild(scoreItem(item));
  for (const item of state.config.talk_scoring?.negative || []) negative.appendChild(scoreItem(item));
}

function scoreItem(item) {
  const row = document.createElement("div");
  row.className = "score-item";
  const value = item.effect || (item.score ?? "");
  const modeValue = item.score_by_mode ? Object.entries(item.score_by_mode).map(([k, v]) => `${k}:${v}`).join(" / ") : value;
  row.innerHTML = `<div><strong>${escapeHtml(item.name)}</strong><span>${item.effect ? "规则" : "评分"}</span></div><span class="score-value">${escapeHtml(modeValue)}</span>`;
  return row;
}

function renderLayers() {
  const root = $("memoryLayers");
  root.innerHTML = "";
  const entries = Object.entries(state.config.memory_layers || {});
  const enabledCount = entries.filter(([, layer]) => layer.enabled).length;
  $("memoryState").textContent = `${enabledCount}/${entries.length} 已打开`;
  for (const [key, layer] of entries) {
    const locked = key === "fact_review";
    const card = document.createElement("article");
    card.className = "layer-card";
    card.innerHTML = `<div class="layer-top"><div><strong>${layerNames[key] || key}</strong><span>${key}</span></div><span class="pill ${layer.enabled ? "ok" : ""}">${layer.status}</span></div><p class="muted">${escapeHtml(layer.description || "")}</p><label class="switch-label"><input data-layer="${key}" type="checkbox" ${layer.enabled ? "checked" : ""} ${locked ? "disabled" : ""}><span>${locked ? "自动" : layer.enabled ? "开" : "关"}</span></label>`;
    root.appendChild(card);
  }
  fillSemanticExtractForm();
  renderSemanticRuns();
  renderSemanticDetails();
}

function syncLayersFromForm() {
  for (const input of document.querySelectorAll("[data-layer]")) {
    const key = input.getAttribute("data-layer");
    state.config.memory_layers[key].enabled = input.checked;
  }
  if (state.config.memory_layers?.fact_review) state.config.memory_layers.fact_review.enabled = true;
  syncSemanticExtractFromForm();
}

function fillSemanticExtractForm() {
  const settings = state.config?.semantic_extract || {};
  if (!$("semanticEnabled")) return;
  $("semanticEnabled").checked = Boolean(settings.enabled);
  $("semanticInterval").value = settings.interval_seconds ?? 10;
  $("semanticMinNew").value = settings.min_new_messages ?? 5;
  $("semanticLimit").value = settings.limit ?? 60;
  $("semanticBatch").value = settings.batch_size ?? 5;
  renderChatSelect("semanticChat", settings.chat_username || "", true);
}

function syncSemanticExtractFromForm() {
  if (!$("semanticEnabled") || !state.config) return;
  state.config.semantic_extract = {
    ...(state.config.semantic_extract || {}),
    enabled: $("semanticEnabled").checked,
    interval_seconds: Number($("semanticInterval").value || 10),
    min_new_messages: Number($("semanticMinNew").value || 5),
    limit: Number($("semanticLimit").value || 60),
    batch_size: Number($("semanticBatch").value || 5),
    chat_username: $("semanticChat").value || "",
  };
}

function renderSemanticRuns() {
  const runsPayload = state.semanticRuns || {};
  const runState = runsPayload.state || {};
  const statePill = $("extractRunState");
  if (statePill) {
    statePill.className = `pill ${runState.running ? "warn" : runState.ok === false ? "bad" : "ok"}`;
    statePill.textContent = runState.running ? "抽取中" : runState.last_skip_reason ? "等待新消息" : runState.ok === false ? "异常" : "正常";
  }
  const root = $("semanticRunList");
  if (!root) return;
  const runs = runsPayload.runs || [];
  const meta = [
    `检查 ${runState.last_checked_at || "--"}`,
    `新增 ${fmtNumber(runState.last_new_messages || 0)}`,
    runState.last_skip_reason ? `跳过 ${runState.last_skip_reason}` : "",
    runState.last_error ? `错误 ${runState.last_error}` : "",
  ].filter(Boolean);
  root.innerHTML = `<div class="run-meta">${meta.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>`;
  if (!runs.length) {
    root.insertAdjacentHTML("beforeend", `<div class="empty-state">暂无抽取运行记录</div>`);
    return;
  }
  for (const run of runs.slice(0, 5)) {
    const row = document.createElement("div");
    const hasWarnings = Boolean(run.error_summary || run.error);
    row.className = `run-row ${run.ok ? hasWarnings ? "warn" : "ok" : "bad"}`;
    const details = run.details || {};
    const localRefresh = details.local_people_refresh?.people_profiles
      ? ` · 本地画像 ${fmtNumber(details.local_people_refresh.people_profiles)}`
      : "";
    const errorText = run.error_summary || summarizeRunDetails(details) || run.error || "";
    row.innerHTML = `
      <div><strong>#${escapeHtml(run.run_id)} ${run.ok ? hasWarnings ? "部分成功" : "成功" : "异常"}</strong><span>${escapeHtml(run.started_at || "")}</span></div>
      <div><span>${fmtNumber(run.message_count)} 条</span><small>${escapeHtml(details.trigger || "manual")} · 批 ${escapeHtml(details.batch_size || "--")}</small></div>
      <div><span>${fmtNumber(run.facts_count)} 事实 · ${fmtNumber(run.people_count)} 人物 · ${fmtNumber(run.graph_edges_count)} 关系${escapeHtml(localRefresh)}</span><small>${escapeHtml(errorText)}</small></div>
    `;
    root.appendChild(row);
  }
}

function summarizeRunDetails(details) {
  const batches = details?.batches || [];
  if (!batches.length) return "";
  const lengthStops = batches.filter((item) => item.llm?.finish_reason === "length").length;
  const retried = batches.filter((item) => item.retry_strategy).length;
  const bits = [];
  if (lengthStops) bits.push(`${lengthStops} 批被截断`);
  if (retried) bits.push(`${retried} 批已拆分重试`);
  return bits.join(" · ");
}

function renderOverviewMemory() {
  const root = $("overviewMemoryList");
  if (!root) return;
  const semantic = state.semantic || {};
  const items = [];
  for (const summary of semantic.summaries || []) items.push({ title: "群摘要", meta: summary.chat_display_name || "群聊", text: summary.summary, tags: summary.topics || [] });
  for (const person of semantic.people || []) items.push({ title: "人物偏好", meta: person.display_name || person.person_key, text: formatObjectValue(person.preferences || person.traits || "已识别人物"), tags: [] });
  for (const fact of semantic.facts || []) items.push({ title: "长期事实", meta: fact.subject, text: `${fact.predicate}：${fact.object}`, tags: [fact.category].filter(Boolean) });
  if (!items.length) items.push({ title: "可管理记忆", meta: "等待抽取", text: "暂无长期记忆，点击抽取记忆后会自动生成摘要、人物偏好、事实和关系边。", tags: [] });
  root.innerHTML = "";
  for (const item of items.slice(0, 4)) {
    const card = document.createElement("details");
    card.className = "memory review-memory";
    card.innerHTML = `
      <summary><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.meta || "")}</span></summary>
      <p>${escapeHtml(item.text || "")}</p>
      ${renderTags(item.tags)}
      <button class="mini-btn" type="button">进入记忆图谱</button>
    `;
    card.querySelector("button").addEventListener("click", (event) => {
      event.preventDefault();
      switchView("memory");
    });
    root.appendChild(card);
  }
}

function renderOverviewServices() {
  const root = $("overviewServiceList");
  if (!root) return;
  const services = state.suite?.services || [];
  if (!services.length) return renderEmpty(root, "服务状态加载中");
  root.innerHTML = "";
  for (const service of services.slice(0, 6)) {
    const containerAvailable = service.container?.available !== false;
    const ok = Boolean(service.health?.ok && (!containerAvailable || service.container?.ok));
    const row = document.createElement("div");
    row.className = `service-mini ${ok ? "ok" : "bad"}`;
    row.innerHTML = `<div><strong>${escapeHtml(service.name || service.id)}</strong><span>${escapeHtml(service.description || "")}</span></div><em>${ok ? "正常" : "异常"}</em>`;
    root.appendChild(row);
  }
}

function renderSemanticDetails() {
  const semantic = state.semantic || {};
  renderMemoryConsole();
  renderSummaries(semantic.summaries || []);
  renderPeople(semantic.people || []);
  renderFacts(semantic.facts || []);
  renderEdges(semantic.edges || []);
}

function renderMemoryConsole() {
  const semantic = state.semantic || {};
  const totals = semantic.totals || {};
  const people = activeMemoryItems(semantic.people || []);
  const facts = activeMemoryItems(semantic.facts || []);
  const summaries = activeMemoryItems(semantic.summaries || []);
  const edges = activeMemoryItems(semantic.edges || []);
  setText("memoryPeopleCount", fmtNumber(people.length));
  setText("memoryFactsCount", fmtNumber(totals.facts || facts.length));
  setText("memorySummaryCount", fmtNumber(summaries.length));
  setText("memoryEdgeCount", fmtNumber(totals.edges || edges.length));
  setText("memoryPeopleHint", `${fmtNumber(people.filter((item) => !item.inferred).length)} 个 LLM 画像`);
  const latest = latestMemoryUpdate([...people, ...facts, ...summaries, ...edges]);
  setText("memoryFreshness", latest ? relativeDate(latest) : "--");
  setText("memoryFreshnessHint", latest ? "最近一次记忆更新" : "等待抽取");
  renderMemoryPeople(people, facts, edges);
  renderMemoryFacts(facts);
  renderMemoryStories(summaries, facts, people);
  renderMemoryTags(summaries, facts, people, edges);
  renderMemoryRelations(people, facts, edges, summaries);
}

function activeMemoryItems(items) {
  return (items || []).filter((item) => item.status !== "disabled");
}

function latestMemoryUpdate(items) {
  const times = items
    .map((item) => Date.parse(item.updated_at || "") || Number(item.latest_time || item.end_time || item.last_seen_time || 0) * 1000)
    .filter((value) => Number.isFinite(value) && value > 0);
  return times.length ? Math.max(...times) : 0;
}

function relativeDate(ms) {
  const diff = Date.now() - Number(ms);
  if (!Number.isFinite(diff) || diff < 0) return "刚刚";
  if (diff < 60_000) return `${Math.max(1, Math.round(diff / 1000))}s`;
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m`;
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h`;
  return `${Math.round(diff / 86_400_000)}d`;
}

function setText(id, value) {
  const node = $(id);
  if (node) node.textContent = value;
}

function memoryItemId(item, fallback = "") {
  return item.profile_id || item.fact_id || item.edge_id || item.chat_username || item.item_id || fallback || stableDomId(item.subject, item.predicate, item.object);
}

function renderMemoryPeople(people, facts, edges) {
  const grid = $("memoryPeopleGrid");
  const detail = $("memoryPersonDetail");
  if (!grid || !detail) return;
  const term = ($("memoryPeopleSearch")?.value || "").trim().toLowerCase();
  const sorted = [...people].sort((a, b) => {
    const scoreA = Number(a.message_count || a.derived?.message_count || 0) + Number(a.confidence || 0) * 100;
    const scoreB = Number(b.message_count || b.derived?.message_count || 0) + Number(b.confidence || 0) * 100;
    return scoreB - scoreA;
  });
  const filtered = sorted.filter((item) => !term || memoryPersonSearchText(item).toLowerCase().includes(term));
  const selectedStillExists = filtered.some((item) => memoryItemId(item) === state.memoryUi.selectedPersonId);
  if (!state.memoryUi.selectedPersonId || !selectedStillExists) state.memoryUi.selectedPersonId = memoryItemId(filtered[0] || sorted[0] || {});
  grid.innerHTML = "";
  if (!filtered.length) {
    renderEmpty(grid, people.length ? "没有匹配的人物画像" : "暂无人物画像，等待下一轮记忆抽取");
  } else {
    filtered.forEach((person, index) => {
      const id = memoryItemId(person, `person-${index}`);
      const card = document.createElement("button");
      card.type = "button";
      card.className = `memory-person-card ${id === state.memoryUi.selectedPersonId ? "active" : ""}`;
      card.dataset.personId = id;
      const initials = personInitial(person);
      const tags = personTags(person, facts, edges).slice(0, 5);
      const avatar = person.avatar_url || "";
      card.innerHTML = `
        <div class="memory-person-top">
          <div class="memory-avatar ${memoryAvatarTone(index)}">${avatar ? `<img src="${escapeAttr(avatar)}" alt="">` : escapeHtml(initials)}</div>
          <div>
            <strong>${escapeHtml(person.display_name || person.person_key || "未知成员")}</strong>
            <span>${escapeHtml(person.person_key || "群成员")}</span>
          </div>
          <em>${formatConfidence(person.confidence)}</em>
        </div>
        <p>${escapeHtml(personSummary(person))}</p>
        ${renderMemoryTagsInline(tags, "person")}
        <div class="memory-person-foot"><span>${fmtNumber(person.message_count || person.derived?.message_count || 0)} 条发言</span><span>${fmtTime(person.latest_time)}</span></div>
      `;
      card.addEventListener("click", () => {
        state.memoryUi.selectedPersonId = id;
        renderMemoryPeople(people, facts, edges);
      });
      grid.appendChild(card);
    });
  }
  const selected = [...people].find((item, index) => memoryItemId(item, `person-${index}`) === state.memoryUi.selectedPersonId) || filtered[0] || people[0];
  renderMemoryPersonDetail(selected, facts, edges);
}

function memoryPersonSearchText(person) {
  return [
    person.display_name,
    person.person_key,
    formatObjectValue(person.preferences),
    formatObjectValue(person.traits),
    ...(person.storyline || []),
    ...(person.recent_snippets || []),
  ].filter(Boolean).join(" ");
}

function personInitial(person) {
  const name = String(person.display_name || person.person_key || "?").trim();
  return name.slice(0, 1).toUpperCase();
}

function memoryAvatarTone(index) {
  return ["green", "blue", "amber", "rose", "violet"][index % 5];
}

function personSummary(person) {
  const story = (person.storyline || []).find(Boolean);
  if (story) return story;
  const traits = formatObjectValue(person.traits || {});
  if (traits) return traits;
  const prefs = formatObjectValue(person.preferences || {});
  if (prefs) return prefs;
  return person.inferred ? "根据聊天片段生成的初始画像，后续抽取会继续补充。" : "已有长期人物画像，等待更多证据丰富细节。";
}

function personTags(person, facts, edges) {
  return personRichTags(person, facts, edges).map((item) => item.label);
}

function personRichTags(person, facts = [], edges = []) {
  const tags = [];
  const add = (label, tone = "topic", weight = 1) => {
    const text = String(label || "").trim();
    if (!text) return;
    tags.push({ label: text, tone, weight });
  };
  for (const key of Object.keys(person.preferences || {})) tags.push(key);
  for (const key of Object.keys(person.preferences || {})) add(key, "preference", 3);
  const traits = person.traits || {};
  if (Array.isArray(traits["性格倾向"])) traits["性格倾向"].slice(0, 4).forEach((item) => add(item, "trait", 3));
  if (Array.isArray(traits.traits)) traits.traits.slice(0, 4).forEach((item) => add(item, "trait", 3));
  const name = person.display_name || person.person_key || "";
  const count = Number(person.message_count || person.derived?.message_count || 0);
  if (count >= 200) add("核心活跃", "confidence", 5);
  else if (count >= 80) add("高频参与", "confidence", 4);
  else if (count >= 30) add("稳定出现", "green", 2);
  if (person.inferred) add("推断画像", "amber", 2);
  else add("长期画像", "blue", 2);
  for (const fact of facts) {
    if (name && (`${fact.subject} ${fact.object}`.includes(name))) add(fact.category || fact.predicate, factTone(fact.category), 2);
  }
  for (const edge of edges) {
    if (name && (`${edge.source_node} ${edge.target_node}`.includes(name))) add(edge.relation, "edge", 2);
  }
  return uniqueTagObjects(tags).slice(0, 18);
}

function uniqueTagObjects(items) {
  const seen = new Map();
  for (const item of items || []) {
    const label = String(item?.label || item || "").trim();
    if (!label) continue;
    const current = seen.get(label);
    if (!current || Number(item.weight || 1) > Number(current.weight || 1)) {
      seen.set(label, { label, tone: item.tone || "topic", weight: Number(item.weight || 1) });
    }
  }
  return [...seen.values()].sort((a, b) => Number(b.weight || 0) - Number(a.weight || 0));
}

function renderMemoryPersonDetail(person, facts, edges) {
  const root = $("memoryPersonDetail");
  if (!root) return;
  if (!person) {
    setText("memoryProfileHint", "暂无可展示成员");
    setText("memoryProfileConfidence", "--");
    return renderEmpty(root, "暂无人物画像。可以先等待自动抽取，或点击顶部抽取记忆。");
  }
  setText("memoryProfileHint", person.display_name || person.person_key || "群成员");
  const confidence = $("memoryProfileConfidence");
  if (confidence) {
    confidence.textContent = `置信 ${formatConfidence(person.confidence)}`;
    confidence.className = `pill ${Number(person.confidence || 0) >= 0.7 ? "ok" : "warn"}`;
  }
  const relatedFacts = facts.filter((fact) => {
    const text = `${fact.subject} ${fact.predicate} ${fact.object}`;
    const name = person.display_name || person.person_key || "";
    return name && text.includes(name);
  }).slice(0, 6);
  const relatedEdges = edges.filter((edge) => {
    const text = `${edge.source_node} ${edge.relation} ${edge.target_node}`;
    const name = person.display_name || person.person_key || "";
    return name && text.includes(name);
  }).slice(0, 6);
  const richTags = personRichTags(person, facts, edges);
  const editableControls = person.inferred
    ? `<div class="memory-inferred-note">这是根据聊天片段生成的推断画像；自动抽取生成正式人物画像后，可以在这里编辑保存。</div>`
    : `
      <article class="memory-card memory-manage-card">
        <label><span>显示名</span><input data-memory-field="display_name" value="${escapeAttr(person.display_name || person.person_key || "")}"></label>
        <label><span>偏好 JSON</span><textarea data-memory-field="preferences" rows="3">${escapeHtml(JSON.stringify(person.preferences || {}, null, 2))}</textarea></label>
        ${renderReviewControls("person", person.profile_id || person.item_id, person)}
      </article>
    `;
  root.innerHTML = `
    <section class="memory-profile-hero">
      <div class="memory-avatar green">${person.avatar_url ? `<img src="${escapeAttr(person.avatar_url)}" alt="">` : escapeHtml(personInitial(person))}</div>
      <div>
        <h3>${escapeHtml(person.display_name || person.person_key || "未知成员")}</h3>
        <p>${escapeHtml(person.person_key || "群成员")} · ${fmtNumber(person.message_count || person.derived?.message_count || 0)} 条相关发言</p>
      </div>
    </section>
    ${memoryDetailSection("画像标签", renderMemoryTagObjects(richTags))}
    ${memoryDetailSection("核心画像", `<p>${escapeHtml(personSummary(person))}</p>`)}
    ${memoryDetailSection("属性", memoryKvGrid([
      ["最近活跃", fmtTime(person.latest_time) || "未知"],
      ["画像来源", person.inferred ? "聊天片段推断" : "LLM 长期画像"],
      ["更新时间", person.updated_at || "--"],
      ["状态", person.status || "active"],
    ]))}
    ${memoryDetailSection("性格归纳", renderMemoryObject(person.traits, "trait"))}
    ${memoryDetailSection("偏好", renderMemoryObject(person.preferences, "preference"))}
    ${memoryDetailSection("故事线", renderMemoryTimeline(person.storyline || []))}
    ${memoryDetailSection("最近证据片段", renderMemoryQuotes(person.recent_snippets || person.evidence || []))}
    ${memoryDetailSection("关联事实", relatedFacts.length ? relatedFacts.map((fact) => `<div class="memory-mini-fact"><strong>${escapeHtml(fact.subject)}</strong><span>${escapeHtml(`${fact.predicate} ${fact.object}`)}</span></div>`).join("") : `<p class="muted">暂无直接关联事实。</p>`)}
    ${memoryDetailSection("关系", relatedEdges.length ? relatedEdges.map((edge) => `<div class="memory-mini-fact"><strong>${escapeHtml(nodeLabel(edge.source_node))}</strong><span>${escapeHtml(`${edge.relation} -> ${nodeLabel(edge.target_node)}`)}</span></div>`).join("") : `<p class="muted">暂无直接关系边。</p>`)}
    ${editableControls}
  `;
}

function renderMemoryFacts(facts) {
  const lanesRoot = $("memoryFactLanes");
  const detailRoot = $("memoryFactDetail");
  if (!lanesRoot || !detailRoot) return;
  const term = ($("memoryFactSearch")?.value || "").trim().toLowerCase();
  const categories = factCategories(facts);
  const filtered = facts.filter((fact) => !term || `${fact.subject} ${fact.predicate} ${fact.object} ${fact.category}`.toLowerCase().includes(term));
  const selectedStillExists = filtered.some((fact) => memoryItemId(fact) === state.memoryUi.selectedFactId);
  if (!state.memoryUi.selectedFactId || !selectedStillExists) state.memoryUi.selectedFactId = memoryItemId(filtered[0] || facts[0] || {});
  renderFactFilters(categories);
  renderFactAutoStatus(facts);
  lanesRoot.innerHTML = "";
  if (!filtered.length) {
    renderEmpty(lanesRoot, facts.length ? "没有匹配的事实" : "暂无长期事实，等待自动抽取。");
  } else {
    for (const category of categories.slice(0, 4)) {
      const laneFacts = filtered.filter((fact) => (fact.category || "other") === category.key);
      if (!laneFacts.length) continue;
      const lane = document.createElement("section");
      lane.className = `memory-fact-lane ${category.tone}`;
      lane.innerHTML = `<h4>${escapeHtml(category.label)} <span>${fmtNumber(laneFacts.length)}</span></h4><div class="memory-fact-list"></div>`;
      const list = lane.querySelector(".memory-fact-list");
      for (const fact of laneFacts.slice(0, 12)) {
        const id = memoryItemId(fact);
        const card = document.createElement("button");
        card.type = "button";
        card.className = `memory-fact-card ${id === state.memoryUi.selectedFactId ? "active" : ""}`;
        card.dataset.factId = id;
        card.innerHTML = `
          <strong>${escapeHtml(fact.subject || "事实")}</strong>
          <p>${escapeHtml(`${fact.predicate || ""} ${fact.object || ""}`.trim())}</p>
          <div class="memory-fact-meta"><span>${formatConfidence(fact.confidence)}</span><span>${escapeHtml(fact.updated_at || "")}</span></div>
          ${renderMemoryTagsInline(["自动事实", fact.reviewed_at ? "已人工复核" : "未复核", fact.category, confidenceLabel(fact.confidence)], category.tone)}
        `;
        card.addEventListener("click", () => {
          state.memoryUi.selectedFactId = id;
          renderMemoryFacts(facts);
        });
        list.appendChild(card);
      }
      lanesRoot.appendChild(lane);
    }
  }
  const selected = facts.find((fact) => memoryItemId(fact) === state.memoryUi.selectedFactId) || filtered[0] || facts[0];
  renderMemoryFactDetail(selected);
}

function renderFactAutoStatus(facts) {
  const root = $("memoryFactAutoStatus");
  if (!root) return;
  const totalFacts = Number(state.semantic?.totals?.facts || facts.length || 0);
  const settings = state.config?.semantic_extract || {};
  const runState = state.semanticRuns?.state || {};
  const latestRun = (state.semanticRuns?.runs || [])[0] || {};
  const lastCounts = runState.last_counts || {};
  const running = Boolean(runState.running);
  const enabled = settings.enabled !== false;
  const statusClass = running ? "warn" : !enabled || runState.ok === false ? "bad" : "ok";
  const statusText = running ? "自动事实抽取中" : !enabled ? "自动抽取已关闭" : runState.last_skip_reason ? "等待新消息" : runState.ok === false ? "自动抽取异常" : "自动更新正常";
  const bits = [
    `事实库 ${fmtNumber(totalFacts)} 条`,
    totalFacts > facts.length ? `当前展示 ${fmtNumber(facts.length)} 条` : "",
    `间隔 ${fmtNumber(settings.interval_seconds ?? 10)} 秒`,
    `新消息阈值 ${fmtNumber(settings.min_new_messages ?? 5)} 条`,
    runState.last_finished_at ? `上次完成 ${escapeHtml(runState.last_finished_at)}` : "",
    runState.last_skip_reason ? `状态 ${escapeHtml(runState.last_skip_reason)}` : "",
    runState.last_error ? `错误 ${escapeHtml(runState.last_error)}` : "",
  ].filter(Boolean);
  root.innerHTML = `
    <div class="auto-orb ${statusClass}"></div>
    <div>
      <strong>${escapeHtml(statusText)}</strong>
      <span>${bits.join(" · ")}</span>
    </div>
    <div class="auto-kpis">
      <span>最近新增事实 <b>${fmtNumber(lastCounts.facts || latestRun.facts_count || 0)}</b></span>
      <span>本地兜底 <b>${fmtNumber(lastCounts.local_facts || latestRun.details?.local_people_refresh?.local_facts || 0)}</b></span>
    </div>
  `;
}

function factCategories(facts) {
  const labels = {
    preference: ["人物偏好", "green"],
    decision: ["决策共识", "blue"],
    project: ["项目资料", "amber"],
    topic: ["话题", "violet"],
    event: ["事件", "rose"],
    other: ["其他", "gray"],
  };
  const keys = uniqueStrings((facts || []).map((fact) => fact.category || "other"));
  return keys.length ? keys.map((key, index) => {
    const item = labels[key] || [key, ["green", "blue", "amber", "rose", "violet"][index % 5]];
    return { key, label: item[0], tone: item[1], count: facts.filter((fact) => (fact.category || "other") === key).length };
  }) : [{ key: "other", label: "其他", tone: "gray", count: 0 }];
}

function renderFactFilters(categories) {
  const root = $("memoryFactFilters");
  if (!root) return;
  setText("memoryFactFilterCount", fmtNumber(categories.reduce((sum, item) => sum + item.count, 0)));
  root.innerHTML = categories.map((item) => `
    <div class="memory-filter-item ${escapeAttr(item.tone)}">
      <strong>${escapeHtml(item.label)}</strong>
      <span>${fmtNumber(item.count)}</span>
    </div>
  `).join("");
}

function renderMemoryFactDetail(fact) {
  const root = $("memoryFactDetail");
  if (!root) return;
  if (!fact) return renderEmpty(root, "选择一条事实查看证据链和管理操作。");
  root.innerHTML = `
    <section class="memory-fact-detail-head">
      ${renderMemoryTagsInline(["自动事实", fact.reviewed_at ? "已人工复核" : "未复核", fact.category || "other", confidenceLabel(fact.confidence)], factTone(fact.category))}
      <h3>${escapeHtml(fact.subject || "事实")}</h3>
      <p>${escapeHtml(`${fact.predicate || ""} ${fact.object || ""}`.trim())}</p>
    </section>
    ${memoryDetailSection("来源消息", sourceMessageList(fact.source_messages || []) || renderMemoryQuotes((fact.source_message_uids || []).slice(0, 8)))}
    ${memoryDetailSection("属性", memoryKvGrid([
      ["置信度", formatConfidence(fact.confidence)],
      ["分类", fact.category || "other"],
      ["首次出现", fmtTime(fact.first_seen_time) || "--"],
      ["最近更新", fact.updated_at || "--"],
      ["更新方式", fact.reviewed_at ? "自动入库 + 人工复核" : "自动事实入库"],
      ["来源数量", `${fmtNumber((fact.source_messages || fact.source_message_uids || []).length)} 条`],
    ]))}
    <article class="memory-card memory-manage-card">
      <div class="fact-edit-grid">
        <input data-memory-field="subject" value="${escapeAttr(fact.subject || "")}">
        <input data-memory-field="predicate" value="${escapeAttr(fact.predicate || "")}">
        <input data-memory-field="object" value="${escapeAttr(fact.object || "")}">
      </div>
      ${renderReviewControls("fact", fact.fact_id || fact.item_id, fact)}
    </article>
  `;
}

function renderMemoryStories(summaries, facts, people) {
  const root = $("memoryStoryList");
  const tagRoot = $("memoryStoryTags");
  if (!root) return;
  if (tagRoot) {
    const tags = uniqueStrings(summaries.flatMap((item) => item.topics || []).concat(facts.slice(0, 6).map((fact) => fact.category)));
    tagRoot.innerHTML = renderMemoryTagSpans(tags.slice(0, 8), "topic");
  }
  const stories = [];
  for (const summary of summaries) {
    stories.push({
      time: summary.end_time || Date.parse(summary.updated_at || "") / 1000,
      title: summary.chat_display_name || "群摘要",
      text: summary.summary,
      tags: summary.topics || [],
      meta: `${fmtNumber(summary.message_count || 0)} 条消息`,
      tone: "summary",
    });
  }
  for (const fact of facts.slice(0, 10)) {
    stories.push({
      time: fact.last_seen_time || Date.parse(fact.updated_at || "") / 1000,
      title: fact.subject || "长期事实",
      text: `${fact.predicate || ""} ${fact.object || ""}`.trim(),
      tags: [fact.category, confidenceLabel(fact.confidence)].filter(Boolean),
      meta: `事实 · ${formatConfidence(fact.confidence)}`,
      tone: factTone(fact.category),
    });
  }
  for (const person of people.slice(0, 8)) {
    for (const story of (person.storyline || []).slice(0, 2)) {
      stories.push({
        time: person.latest_time || Date.parse(person.updated_at || "") / 1000,
        title: person.display_name || person.person_key || "群成员",
        text: story,
        tags: personTags(person, facts, []).slice(0, 3),
        meta: "人物故事线",
        tone: "person",
      });
    }
  }
  stories.sort((a, b) => Number(b.time || 0) - Number(a.time || 0));
  root.innerHTML = "";
  if (!stories.length) return renderEmpty(root, "暂无群记忆故事线，等待自动抽取。");
  for (const story of stories.slice(0, 18)) {
    const card = document.createElement("article");
    card.className = `memory-story ${story.tone || "summary"}`;
    card.innerHTML = `
      <div class="memory-story-time"><strong>${escapeHtml(story.time ? fmtTime(story.time).split(" ")[1] || fmtTime(story.time) : "--")}</strong><span>${escapeHtml(story.meta || "")}</span></div>
      <div class="memory-story-content">
        <h4>${escapeHtml(story.title || "记忆")}</h4>
        <p>${escapeHtml(story.text || "")}</p>
        ${renderMemoryTagsInline(story.tags || [], story.tone)}
      </div>
    `;
    root.appendChild(card);
  }
}

function renderMemoryTags(summaries, facts, people, edges) {
  const root = $("memoryTagIndex");
  if (!root) return;
  const groups = [
    ["人物", "person", people.map((item) => item.display_name || item.person_key)],
    ["主题", "topic", summaries.flatMap((item) => item.topics || [])],
    ["事实类型", "fact", facts.map((item) => item.category || "other")],
    ["关系", "edge", edges.map((item) => item.relation)],
    ["风险/约束", "risk", facts.filter((item) => /风险|封号|只读|安全|不|禁止/.test(`${item.subject}${item.object}`)).map((item) => item.subject || item.category)],
  ];
  root.innerHTML = groups.map(([title, type, tags]) => `
    <section class="memory-tag-group">
      <h4>${escapeHtml(title)}</h4>
      <div class="memory-tag-row">${renderMemoryTagSpans(uniqueStrings(tags).slice(0, 18), type)}</div>
    </section>
  `).join("");
}

function renderMemoryRelations(people, facts, edges, summaries) {
  const focusRoot = $("memoryFocusList");
  if (!focusRoot) return;
  const focuses = [
    ...people.slice(0, 12).map((person, index) => ({
      id: `person:${memoryItemId(person, String(index))}`,
      label: person.display_name || person.person_key || "群成员",
      sub: `${fmtNumber(person.message_count || person.derived?.message_count || 0)} 条发言`,
      type: "person",
      source: person,
    })),
    ...summaries.slice(0, 3).map((summary) => ({
      id: `summary:${summary.chat_username || summary.chat_display_name}`,
      label: summary.chat_display_name || "群摘要",
      sub: `${fmtNumber(summary.message_count || 0)} 条消息`,
      type: "summary",
      source: summary,
    })),
  ];
  if (!state.memoryUi.selectedFocusId || !focuses.some((item) => item.id === state.memoryUi.selectedFocusId)) {
    state.memoryUi.selectedFocusId = focuses[0]?.id || "";
  }
  focusRoot.innerHTML = "";
  if (!focuses.length) {
    renderEmpty(focusRoot, "暂无可聚焦对象");
  } else {
    focuses.forEach((focus, index) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = `memory-focus-item ${focus.id === state.memoryUi.selectedFocusId ? "active" : ""}`;
      item.innerHTML = `<div class="memory-avatar ${memoryAvatarTone(index)}">${escapeHtml(String(focus.label).slice(0, 1))}</div><div><strong>${escapeHtml(focus.label)}</strong><span>${escapeHtml(focus.sub)}</span></div>`;
      item.addEventListener("click", () => {
        state.memoryUi.selectedFocusId = focus.id;
        renderMemoryRelations(people, facts, edges, summaries);
      });
      focusRoot.appendChild(item);
    });
  }
  const selected = focuses.find((item) => item.id === state.memoryUi.selectedFocusId) || focuses[0];
  renderMemoryRelationCanvas(selected, people, facts, edges, summaries);
}

function renderMemoryRelationCanvas(focus, people, facts, edges, summaries) {
  const canvas = $("memoryRelationCanvas");
  const detail = $("memoryRelationDetail");
  if (!canvas || !detail) return;
  if (!focus) {
    renderEmpty(canvas, "暂无关系数据");
    renderEmpty(detail, "选择对象后显示关系摘要。");
    return;
  }
  const label = focus.label;
  const relatedFacts = facts.filter((fact) => `${fact.subject} ${fact.object} ${fact.predicate}`.includes(label)).slice(0, 5);
  const relatedEdges = edges.filter((edge) => `${edge.source_node} ${edge.target_node} ${edge.relation}`.includes(label)).slice(0, 8);
  const relatedPeople = people.filter((person) => {
    const name = person.display_name || person.person_key || "";
    return name && name !== label && relatedEdges.some((edge) => `${edge.source_node} ${edge.target_node}`.includes(name));
  }).slice(0, 5);
  const fallbackPeople = people.filter((person) => (person.display_name || person.person_key) !== label).slice(0, Math.max(0, 5 - relatedPeople.length));
  const peopleGroup = uniqueRelationItems([...relatedPeople, ...fallbackPeople].map((person) => ({
    title: person.display_name || person.person_key || "成员",
    sub: `${fmtNumber(person.message_count || person.derived?.message_count || 0)} 条发言`,
    tone: "person",
  }))).slice(0, 5);
  const factGroup = relatedFacts.map((fact) => ({
    title: fact.subject || "事实",
    sub: `${fact.predicate || fact.category || "事实"} · ${formatConfidence(fact.confidence)}`,
    tone: factTone(fact.category),
  }));
  const relationGroup = relatedEdges.map((edge) => ({
    title: edge.relation || "关系",
    sub: `${nodeLabel(edge.source_node)} -> ${nodeLabel(edge.target_node)}`,
    tone: "edge",
  }));
  const topics = summaries.flatMap((summary) => summary.topics || []).slice(0, 5);
  const topicGroup = topics.map((topic) => ({ title: topic, sub: "群主题", tone: "topic" }));
  const groups = [
    { title: "相关成员", tone: "person", items: peopleGroup },
    { title: "关系边", tone: "edge", items: relationGroup },
    { title: "事实证据", tone: "fact", items: factGroup },
    { title: "群主题", tone: "topic", items: topicGroup },
  ];
  const nodeCount = groups.reduce((sum, group) => sum + group.items.length, 0);
  canvas.innerHTML = `
    <div class="relation-board">
      <section class="relation-core">
        <span>${escapeHtml(focus.type === "person" ? "人物" : "摘要")}</span>
        <strong>${escapeHtml(label)}</strong>
        <small>${escapeHtml(focus.sub || "聚焦对象")}</small>
      </section>
      ${groups.map((group) => `
        <section class="relation-column ${escapeAttr(group.tone)}">
          <h4>${escapeHtml(group.title)} <span>${fmtNumber(group.items.length)}</span></h4>
          <div>
            ${group.items.length ? group.items.map((item) => `
              <article class="relation-item ${escapeAttr(item.tone)}">
                <strong>${escapeHtml(item.title)}</strong>
                <span>${escapeHtml(item.sub || "")}</span>
              </article>
            `).join("") : `<p class="muted">暂无直接关联</p>`}
          </div>
        </section>
      `).join("")}
    </div>
  `;
  detail.innerHTML = `
    ${memoryDetailSection("核心对象", `<p>${escapeHtml(focus.label)} 当前关联 ${fmtNumber(nodeCount)} 个可读节点。新版关系视图按“成员、关系、事实、主题”分区展示，不再用难读的散点图。</p>`)}
    ${memoryDetailSection("关联事实", relatedFacts.length ? relatedFacts.map((fact) => `<div class="memory-mini-fact"><strong>${escapeHtml(fact.subject)}</strong><span>${escapeHtml(`${fact.predicate} ${fact.object}`)}</span></div>`).join("") : `<p class="muted">暂无直接事实。</p>`)}
    ${memoryDetailSection("关系边", relatedEdges.length ? relatedEdges.map((edge) => `<div class="memory-mini-fact"><strong>${escapeHtml(nodeLabel(edge.source_node))}</strong><span>${escapeHtml(`${edge.relation} -> ${nodeLabel(edge.target_node)}`)}</span></div>`).join("") : `<p class="muted">暂无直接关系边。</p>`)}
    ${memoryDetailSection("主题", renderMemoryTagSpans(topics, "topic"))}
  `;
}

function uniqueRelationItems(items) {
  const seen = new Set();
  return (items || []).filter((item) => {
    const key = `${item.title}::${item.sub}`;
    if (!item.title || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function memoryDetailSection(title, html) {
  if (!html) return "";
  return `<section class="memory-detail-section"><h4>${escapeHtml(title)}</h4>${html}</section>`;
}

function memoryKvGrid(rows) {
  return `<div class="memory-kv">${rows.map(([key, value]) => `<div><span>${escapeHtml(key)}</span><strong>${escapeHtml(value || "--")}</strong></div>`).join("")}</div>`;
}

function renderMemoryObject(value, type = "topic") {
  if (!value || (typeof value === "object" && !Object.keys(value).length)) return `<p class="muted">暂无。</p>`;
  if (Array.isArray(value)) return renderMemoryTagsInline(value, type);
  if (typeof value === "object") {
    return Object.entries(value).map(([key, raw]) => `
      <div class="memory-object-row">
        <strong>${escapeHtml(key)}</strong>
        <div>${Array.isArray(raw) ? renderMemoryTagsInline(raw, type) : `<span>${escapeHtml(formatObjectValue(raw))}</span>`}</div>
      </div>
    `).join("");
  }
  return `<p>${escapeHtml(value)}</p>`;
}

function renderMemoryTimeline(items) {
  if (!Array.isArray(items) || !items.length) return `<p class="muted">暂无故事线。</p>`;
  return `<div class="memory-timeline">${items.slice(0, 8).map((item) => `<div><strong>${escapeHtml(String(item).slice(0, 18))}</strong><span>${escapeHtml(item)}</span></div>`).join("")}</div>`;
}

function renderMemoryQuotes(items) {
  if (!Array.isArray(items) || !items.length) return `<p class="muted">暂无证据片段。</p>`;
  return items.slice(0, 8).map((item) => `<blockquote class="memory-quote">${escapeHtml(formatEvidenceItem(item))}</blockquote>`).join("");
}

function formatEvidenceItem(item) {
  if (item && typeof item === "object") return item.text || item.message_uid || JSON.stringify(item);
  return String(item || "");
}

function renderMemoryTagsInline(tags, type = "topic") {
  const safe = uniqueStrings(tags).filter(Boolean).slice(0, 8);
  if (!safe.length) return "";
  return `<div class="memory-tag-row">${renderMemoryTagSpans(safe, type)}</div>`;
}

function renderMemoryTagSpans(tags, type = "topic") {
  return uniqueStrings(tags).filter(Boolean).map((tag, index) => `<span class="memory-tag ${tagClass(type, tag, index)}">${escapeHtml(String(tag))}</span>`).join("");
}

function renderMemoryTagObjects(tags) {
  const safe = (tags || []).filter((item) => item?.label).slice(0, 18);
  if (!safe.length) return `<p class="muted">暂无标签。</p>`;
  return `<div class="memory-tag-row rich">${safe.map((tag) => `<span class="memory-tag ${tagClass(tag.tone, tag.label)} weight-${Math.min(5, Math.max(1, Math.round(tag.weight || 1)))}">${escapeHtml(tag.label)}</span>`).join("")}</div>`;
}

function tagClass(type, tag, index = 0) {
  const text = String(tag || "");
  if (/风险|封号|只读|安全|禁止|异常|冲突|不/.test(text) || type === "risk") return "risk";
  if (/高|9\d%|100%|置信/.test(text)) return "confidence";
  if (type === "person") return "person";
  if (type === "fact") return "fact";
  if (type === "edge") return "edge";
  if (type === "preference") return "preference";
  if (type === "trait") return "trait";
  if (type === "summary") return "summary";
  return ["topic", "blue", "amber", "violet"][index % 4];
}

function confidenceLabel(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "置信未知";
  return number >= 0.8 ? "高置信" : number >= 0.55 ? "中置信" : "低置信";
}

function factTone(category) {
  return {
    preference: "green",
    decision: "blue",
    project: "amber",
    topic: "violet",
    event: "rose",
    other: "gray",
  }[category || "other"] || "gray";
}

function uniqueStrings(items) {
  const seen = new Set();
  const output = [];
  for (const item of items || []) {
    const text = String(item ?? "").trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    output.push(text);
  }
  return output;
}

function renderSummaries(items) {
  const root = $("summaryPreview");
  root.innerHTML = "";
  if (!items.length) return renderEmpty(root, "暂无群摘要");
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "memory-card";
    card.innerHTML = `
      <div class="memory-card-head"><strong>${escapeHtml(item.chat_display_name || "群摘要")}</strong><span class="pill ${item.status === "disabled" ? "bad" : "ok"}">${escapeHtml(item.status || "active")}</span></div>
      <textarea data-memory-field="summary">${escapeHtml(item.summary || "")}</textarea>
      ${renderTags(item.topics || [])}
      ${renderReviewControls("summary", item.chat_username, item)}
    `;
    root.appendChild(card);
  }
}

function renderPeople(items) {
  const root = $("peoplePreview");
  root.innerHTML = "";
  if (!items.length) return renderEmpty(root, "暂无人物偏好");
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "memory-card";
    card.innerHTML = `
      <div class="memory-card-head"><strong>${escapeHtml(item.display_name || item.person_key)}</strong><span class="pill ${item.status === "disabled" ? "bad" : "ok"}">置信 ${formatConfidence(item.confidence)}</span></div>
      <label><span>显示名</span><input data-memory-field="display_name" value="${escapeAttr(item.display_name || item.person_key || "")}"></label>
      <label><span>偏好 JSON</span><textarea data-memory-field="preferences" rows="3">${escapeHtml(JSON.stringify(item.preferences || {}, null, 2))}</textarea></label>
      ${renderReviewControls("person", item.profile_id, item)}
    `;
    root.appendChild(card);
  }
}

function renderFacts(items) {
  const root = $("factPreview");
  root.innerHTML = "";
  if (!items.length) return renderEmpty(root, "暂无长期事实");
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "memory-card";
    card.innerHTML = `
      <div class="memory-card-head"><strong>${escapeHtml(item.subject)}</strong><span class="pill ${item.status === "disabled" ? "bad" : ""}">${escapeHtml(item.category || "other")}</span></div>
      <div class="fact-edit-grid">
        <input data-memory-field="subject" value="${escapeAttr(item.subject || "")}">
        <input data-memory-field="predicate" value="${escapeAttr(item.predicate || "")}">
        <input data-memory-field="object" value="${escapeAttr(item.object || "")}">
      </div>
      ${renderReviewControls("fact", item.fact_id, item)}
    `;
    root.appendChild(card);
  }
}

function renderEdges(items) {
  const root = $("edgePreview");
  root.innerHTML = "";
  if (!items.length) return renderEmpty(root, "暂无关系边");
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "memory-card";
    const id = item.edge_id || item.item_id || stableDomId(item.source_node, item.relation, item.target_node);
    card.innerHTML = `
      <div class="edge-edit-grid">
        <input data-memory-field="source_node" value="${escapeAttr(nodeLabel(item.source_node) || "")}">
        <input data-memory-field="relation" value="${escapeAttr(item.relation || "")}">
        <input data-memory-field="target_node" value="${escapeAttr(nodeLabel(item.target_node) || "")}">
      </div>
      <span class="muted">置信 ${formatConfidence(item.confidence)}</span>
      ${renderReviewControls("edge", id, item)}
    `;
    root.appendChild(card);
  }
}

function renderReviewControls(kind, id, item) {
  return `
    <div class="review-controls" data-memory-kind="${escapeAttr(kind)}" data-memory-id="${escapeAttr(id || "")}">
      <input data-memory-field="review_note" placeholder="管理备注" value="${escapeAttr(item.review_note || "")}">
      <div class="button-row">
        <button class="mini-btn" type="button" data-memory-action="save">保存</button>
        <button class="mini-btn" type="button" data-memory-action="${item.status === "disabled" ? "activate" : "disable"}">${item.status === "disabled" ? "启用" : "禁用"}</button>
        <button class="mini-btn danger" type="button" data-memory-action="delete">删除</button>
      </div>
    </div>
  `;
}

function stableDomId(...parts) {
  return parts.map((part) => String(part || "").replace(/\s+/g, "-")).join("-");
}

function renderGraph(graph) {
  const nodesRoot = $("graphNodes");
  const edgesRoot = $("graphEdges");
  const leaderboardRoot = $("graphLeaderboard");
  if (!nodesRoot || !edgesRoot) return;
  const graphData = prepareOverviewGraph(graph);
  const nodes = graphData.nodes;
  const edges = graphData.edges;
  const positions = layoutGraph(nodes);
  const world = graphData.world || { width: 1800, height: 1120 };
  const worldChanged = state.graph.worldWidth !== world.width || state.graph.worldHeight !== world.height;
  state.graph.worldWidth = world.width;
  state.graph.worldHeight = world.height;
  if (state.graph.selectedId && !nodes.some((node) => node.id === state.graph.selectedId)) state.graph.selectedId = null;
  if (!state.graph.selectedId) {
    const preferred = nodes.find((node) => node.kind === "person") || nodes.find((node) => node.kind === "summary") || nodes[0];
    state.graph.selectedId = preferred?.id || null;
  }
  state.graph.nodes = nodes;
  state.graph.edges = edges;
  state.graph.positions = positions;
  nodesRoot.innerHTML = "";
  edgesRoot.innerHTML = "";
  edgesRoot.setAttribute("viewBox", `0 0 ${world.width} ${world.height}`);
  if (leaderboardRoot) {
    leaderboardRoot.innerHTML = graphLeaderboardHtml(graphData.leaderboard || nodes);
  }

  edges.forEach((edge, index) => {
    const source = positions.get(edge.source_node);
    const target = positions.get(edge.target_node);
    if (!source || !target) return;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const sx = source.x + source.w / 2;
    const sy = source.y + source.h / 2;
    const tx = target.x + target.w / 2;
    const ty = target.y + target.h / 2;
    const isCoreLink = source.kind === "summary" || target.kind === "summary" || edge.synthetic === true;
    if (isCoreLink) {
      path.setAttribute("d", `M ${sx} ${sy} L ${tx} ${ty}`);
    } else {
      const cx = (sx + tx) / 2;
      const dy = Math.abs(ty - sy);
      const bend = edge.kind === "summary_topic" ? -54 : edge.kind === "fact" ? 54 : (index % 2 ? -44 : 44);
      const cy = (sy + ty) / 2 + bend + Math.min(62, dy * 0.10);
      path.setAttribute("d", `M ${sx} ${sy} C ${cx} ${cy}, ${cx} ${cy}, ${tx} ${ty}`);
    }
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", graphEdgeColor(edge));
    path.setAttribute("stroke-width", isCoreLink ? "2.8" : edge.kind === "edge" ? "2" : "1.6");
    path.style.setProperty("--edge-delay", `${-(index % 9) * 0.42}s`);
    path.style.setProperty("--edge-speed", `${5.8 + (index % 5) * 0.65}s`);
    path.dataset.kind = edge.kind || "";
    path.dataset.source = edge.source_node;
    path.dataset.target = edge.target_node;
    path.dataset.edgeIndex = String(index);
    edgesRoot.appendChild(path);
  });

  for (const node of nodes) {
    const pos = positions.get(node.id);
    if (!pos) continue;
    const div = document.createElement("div");
    const rank = node.kind === "person" ? personRank(node) : "";
    const rankClass = rank ? `rank-${rankClassName(rank)}` : "";
    div.className = `graph-node ${node.kind || "entity"} ${graphNodeTone(node)} ${rankClass} ${node.id === state.graph.selectedId ? "selected" : ""}`;
    div.style.left = `${pos.x}px`;
    div.style.top = `${pos.y}px`;
    div.style.width = `${pos.w}px`;
    div.style.height = `${pos.h}px`;
    div.style.setProperty("--float-delay", `${-((node.id.length + nodes.indexOf(node) * 7) % 17) * 0.31}s`);
    div.style.setProperty("--float-speed", `${7.2 + (nodes.indexOf(node) % 6) * 0.45}s`);
    div.dataset.kind = node.kind || "entity";
    div.dataset.id = node.id;
    if (rank) div.dataset.rank = rank;
    div.tabIndex = 0;
    div.setAttribute("role", "button");
    div.setAttribute("aria-label", `${graphKindName(node.kind)} ${node.label || node.id}`);
    div.innerHTML = graphNodeHtml(node);
    div.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
    });
    div.addEventListener("click", (event) => {
      event.stopPropagation();
      selectGraphNode(node.id);
    });
    div.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      selectGraphNode(node.id);
    });
    nodesRoot.appendChild(div);
  }
  updateGraphFilter();
  renderGraphDetail(selectedGraphNode());
  if (!state.graph.didFit || worldChanged) {
    state.graph.didFit = true;
    setTimeout(fitGraph, 0);
  } else {
    applyGraphTransform();
  }
}

function graphLeaderboardHtml(nodes) {
  const people = nodes
    .filter((node) => node.kind === "person")
    .sort((a, b) => Number(b.meta?.message_count || b.count || 0) - Number(a.meta?.message_count || a.count || 0))
    .slice(0, 10);
  if (!people.length) return "";
  return `
    <div class="leaderboard-head">
      <span>群聊发言榜</span>
      <strong>Top 10</strong>
    </div>
    ${people.map((node, index) => {
      const count = Number(node.meta?.message_count || node.count || 0);
      const rank = personRank(node);
      const rankClass = rankClassName(rank);
      const displayName = node.label || node.meta?.display_name || node.meta?.contact_display_name || node.id;
      const username = node.meta?.username || node.meta?.person_key || "";
      const avatar = node.meta?.avatar_url || "";
      const podiumClass = index < 3 ? `podium podium-${index + 1}` : "standard";
      const crown = index < 3 ? `<span class="leader-crown" aria-hidden="true"><i></i><i></i><i></i></span>` : "";
      const seat = index === 0 ? "冠军席" : index === 1 ? "银翼席" : index === 2 ? "铜辉席" : "活跃席";
      return `
        <button type="button" class="leader-row ${podiumClass} rank-${rankClass}" data-place="${index + 1}" data-leader-node="${escapeAttr(node.id)}">
          <span class="leader-row-glow" aria-hidden="true"></span>
          ${crown}
          <span class="leader-place"><em>${index + 1}</em><small>NO.</small></span>
          <span class="leader-avatar-wrap">
            <span class="avatar-frame avatar-frame-outer" aria-hidden="true"></span>
            <span class="avatar-frame avatar-frame-inner" aria-hidden="true"></span>
            <span class="leader-avatar">${avatar ? `<img src="${escapeAttr(avatar)}" alt="">` : `<i>${escapeHtml(personInitial({ display_name: displayName, person_key: username }))}</i>`}</span>
          </span>
          <span class="leader-main">
            <span class="leader-seat">${escapeHtml(seat)}</span>
            <em>${escapeHtml(displayName)}</em>
            <small>${fmtNumber(count)} 条发言</small>
          </span>
          <b class="leader-rank-badge">${escapeHtml(rank)}</b>
        </button>
      `;
    }).join("")}
  `;
}

function prepareOverviewGraph(graph) {
  const allEdges = graph.edges || [];
  const allNodes = buildGraphNodes(graph.nodes || [], allEdges);
  const summaries = allNodes.filter((node) => node.kind === "summary").sort((a, b) => graphNodeSignal(b) - graphNodeSignal(a));
  const people = allNodes.filter((node) => node.kind === "person").sort((a, b) => graphNodeSignal(b) - graphNodeSignal(a));
  const facts = allNodes.filter((node) => node.kind === "fact" && !hasPlaceholderPersonName(node)).sort((a, b) => graphNodeSignal(b) - graphNodeSignal(a));
  const topics = allNodes.filter((node) => node.kind === "topic").sort((a, b) => graphNodeSignal(b) - graphNodeSignal(a));
  const objects = allNodes.filter((node) => node.kind === "object" && !hasPlaceholderPersonName(node)).sort((a, b) => graphNodeSignal(b) - graphNodeSignal(a));
  const summary = summaries[0] || {
    id: "summary:core",
    label: "群摘要核心",
    kind: "summary",
    count: state.memory?.messages || 0,
    meta: {
      summary: "群摘要核心",
      message_count: state.memory?.messages || 0,
      topics: [],
      open_questions: [],
    },
  };
  const selectedPeople = people.slice(0, 9);
  const leaderboard = people.slice(0, 10);
  const satellites = [...topics.slice(0, 3), ...facts.slice(0, 5), ...objects.slice(0, 2)].slice(0, 8);
  const nodeList = [summary, ...selectedPeople, ...satellites];
  const seen = new Set();
  const nodes = nodeList.filter((node) => {
    if (!node?.id || seen.has(node.id)) return false;
    seen.add(node.id);
    return true;
  });
  const nodeIds = new Set(nodes.map((node) => node.id));
  const existing = allEdges.filter((edge) => nodeIds.has(edge.source_node) && nodeIds.has(edge.target_node));
  const synthetic = [];
  const linkTargets = [...selectedPeople, ...satellites].filter((node) => nodeIds.has(node.id));
  for (const node of linkTargets) {
    const hasEdge = existing.some((edge) =>
      (edge.source_node === summary.id && edge.target_node === node.id) ||
      (edge.target_node === summary.id && edge.source_node === node.id)
    );
    if (!hasEdge) {
      synthetic.push({
        source_node: summary.id,
        target_node: node.id,
        relation: node.kind === "person" ? "人物画像" : node.kind === "topic" ? "群主题" : "关联记忆",
        confidence: node.meta?.confidence || 0.6,
        kind: node.kind === "person" ? "preference" : node.kind === "fact" || node.kind === "object" ? "fact" : "summary_topic",
        synthetic: true,
      });
    }
  }
  const edges = [...synthetic, ...existing].filter((edge, index, list) => {
    const key = `${edge.source_node}->${edge.relation}->${edge.target_node}`;
    return list.findIndex((item) => `${item.source_node}->${item.relation}->${item.target_node}` === key) === index;
  }).slice(0, 18);
  return { nodes, edges, leaderboard, world: { width: 1800, height: 1120 } };
}

function hasPlaceholderPersonName(node) {
  const meta = node.meta || {};
  const factText = Array.isArray(meta.facts)
    ? meta.facts.map((fact) => `${fact?.subject || ""} ${fact?.predicate || ""} ${fact?.object || ""}`).join(" ")
    : "";
  const text = [node.label, node.id, meta.subject, meta.object, factText].map((value) => String(value || "")).join(" ");
  return /(^|\s|:)成员[A-Z甲乙丙丁一二三四五六七八九十]\b/.test(text);
}

function prepareOverviewGraphLegacy(graph) {
  const allEdges = graph.edges || [];
  const allNodes = buildGraphNodes(graph.nodes || [], allEdges);
  const primary = [];
  const byKind = new Map();
  for (const node of allNodes) {
    const kind = node.kind || "entity";
    if (!byKind.has(kind)) byKind.set(kind, []);
    byKind.get(kind).push(node);
  }
  const sortBySignal = (items) => [...items].sort((a, b) => graphNodeSignal(b) - graphNodeSignal(a));
  const take = (kind, count) => sortBySignal(byKind.get(kind) || []).slice(0, count);
  primary.push(...take("summary", 1));
  primary.push(...take("person", 4));
  primary.push(...take("fact", 4));
  primary.push(...take("topic", 2));
  primary.push(...take("story", 2));
  primary.push(...take("trait", 1));
  primary.push(...take("preference", 1));
  primary.push(...take("object", 2));
  if (primary.length < 14) primary.push(...sortBySignal(allNodes.filter((node) => !primary.includes(node))).slice(0, 14 - primary.length));
  const seen = new Set();
  const nodes = primary.filter((node) => {
    if (!node.id || seen.has(node.id)) return false;
    seen.add(node.id);
    return true;
  }).slice(0, 17);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const connected = allEdges.filter((edge) => nodeIds.has(edge.source_node) && nodeIds.has(edge.target_node));
  const summary = nodes.find((node) => node.kind === "summary") || nodes[0];
  const synthetic = [];
  if (summary) {
    for (const node of nodes) {
      if (node.id === summary.id) continue;
      const hasEdge = connected.some((edge) =>
        (edge.source_node === summary.id && edge.target_node === node.id) ||
        (edge.target_node === summary.id && edge.source_node === node.id)
      );
      if (!hasEdge && ["person", "fact", "topic", "risk", "object"].includes(node.kind || "")) {
        synthetic.push({
          source_node: summary.id,
          target_node: node.id,
          relation: "关联",
          confidence: node.meta?.confidence || 0.5,
          kind: node.kind === "fact" || node.kind === "object" ? "fact" : node.kind === "person" ? "preference" : "summary_topic",
          synthetic: true,
        });
      }
    }
  }
  return { nodes, edges: [...connected, ...synthetic].slice(0, 28) };
}

function graphNodeSignal(node) {
  const meta = node.meta || {};
  return Number(meta.message_count || node.count || 0) + Number(meta.confidence || 0) * 100 + (node.kind === "summary" ? 10000 : 0);
}

function graphEdgeColor(edge) {
  if (edge.kind === "summary_topic") return "rgba(90,255,162,.78)";
  if (edge.kind === "fact") return "rgba(255,207,95,.82)";
  if (edge.kind === "preference") return "rgba(96,246,151,.78)";
  if (edge.kind === "storyline") return "rgba(139,162,255,.66)";
  return "rgba(116,150,255,.66)";
}

function graphNodeHtml(node) {
  const meta = node.meta || {};
  const kind = node.kind || "entity";
  if (kind === "summary") {
    const count = fmtNumber(meta.message_count || node.count || state.memory?.messages || 0);
    const topics = Array.isArray(meta.topics) && meta.topics.length ? `主题：${meta.topics.slice(0, 4).join("、")}` : "";
    return `
      <div class="core-aura core-aura-one" aria-hidden="true"></div>
      <div class="core-aura core-aura-two" aria-hidden="true"></div>
      <div class="core-orb" aria-hidden="true"><span></span></div>
      <strong>群摘要核心</strong>
      <span>${count} 条消息</span>
      ${meta.summary ? `<small class="core-summary-text">${escapeHtml(meta.summary)}</small>` : ""}
      ${topics ? `<em class="core-topic-line">${escapeHtml(topics)}</em>` : ""}
    `;
  }
  if (kind === "person") {
    const count = Number(meta.message_count || node.count || 0);
    const rank = personRank(node);
    const displayName = node.label || meta.display_name || meta.contact_display_name || meta.person_key || node.id;
    const username = meta.username || meta.person_key || "";
    const avatar = meta.avatar_url || "";
    return `
      <i class="person-avatar" aria-hidden="true">${avatar ? `<img src="${escapeAttr(avatar)}" alt="">` : `<span>${escapeHtml(personInitial({ display_name: displayName, person_key: username }))}</span>`}</i>
      <b aria-hidden="true">${escapeHtml(rank)}</b>
      <strong>${escapeHtml(displayName)}</strong>
      <span>${fmtNumber(count)} 发言</span>
      <small>${escapeHtml(personRankLabel(rank))}${username && username !== displayName ? ` · ${escapeHtml(username)}` : ""}</small>
    `;
  }
  const sub = {
    person: `${fmtNumber(meta.message_count || node.count || 0)} 条发言`,
    fact: `${meta.predicate || "事实"} · ${formatConfidence(meta.confidence)}`,
    topic: "群主题",
    story: "记忆节点",
    trait: "性格倾向",
    preference: "人物特征",
    object: "事实对象",
    entity: "关系实体",
  }[kind] || kind;
  const body = graphNodeBody(node);
  return `
    <i aria-hidden="true"></i>
    <b aria-hidden="true"></b>
    <strong>${escapeHtml(node.label || node.id)}</strong>
    <span>${escapeHtml(sub)}</span>
    ${body ? `<small>${escapeHtml(body)}</small>` : ""}
  `;
}

function personRank(node) {
  const count = Number(node.meta?.message_count || node.count || 0);
  if (count >= 20000) return "水王";
  if (count >= 10000) return "超神";
  if (count >= 5000) return "SSS";
  if (count >= 2000) return "SS";
  if (count >= 500) return "S";
  if (count >= 100) return "A";
  if (count >= 60) return "B";
  if (count >= 30) return "C";
  return "D";
}

function personRankLabel(rank) {
  return { 水王: "群聊水王", 超神: "超神主宰", SSS: "星河主力", SS: "超级核心", S: "核心贡献者", A: "高活跃成员", B: "稳定参与", C: "低频参与", D: "偶尔冒泡" }[rank] || "群成员";
}

function rankClassName(rank) {
  return { 水王: "water", 超神: "god", SSS: "sss", SS: "ss", S: "s", A: "a", B: "b", C: "c", D: "d" }[rank] || "d";
}

function graphNodeBody(node) {
  const meta = node.meta || {};
  if (node.kind === "summary") return meta.summary || "";
  if (node.kind === "person") return (meta.storyline || [])[0] || formatObjectValue(meta.traits || meta.preferences || "");
  if (node.kind === "fact") return `${meta.predicate || ""} ${meta.object || ""}`.trim();
  if (node.kind === "topic") return meta.summary || "";
  if (node.kind === "story") return meta.story || "";
  if (node.kind === "trait") return meta.trait || "";
  if (node.kind === "object") return (meta.facts || []).map((fact) => `${fact.subject}${fact.predicate || ""}`).join("、");
  if (node.kind === "preference") return formatObjectValue(meta.value || "");
  return "";
}

function buildGraphNodes(nodes, edges) {
  const map = new Map();
  for (const node of nodes) map.set(node.id, { ...node });
  for (const edge of edges) {
    if (!map.has(edge.source_node)) map.set(edge.source_node, { id: edge.source_node, label: nodeLabel(edge.source_node), kind: "entity", count: 1 });
    if (!map.has(edge.target_node)) map.set(edge.target_node, { id: edge.target_node, label: nodeLabel(edge.target_node), kind: "entity", count: 1 });
  }
  return [...map.values()];
}

function layoutGraph(nodes) {
  const positions = new Map();
  const center = { x: 900, y: 560 };
  const summary = nodes.find((node) => node.kind === "summary");
  if (summary) {
    const size = graphNodeSize(summary);
    positions.set(summary.id, { x: center.x - size.w / 2, y: center.y - size.h / 2, ...size, kind: summary.kind });
  }
  const people = nodes.filter((node) => node.kind === "person").sort((a, b) => graphNodeSignal(b) - graphNodeSignal(a));
  const satellites = nodes.filter((node) => node.kind !== "summary" && node.kind !== "person");
  const personSlots = [
    { x: center.x + 82, y: center.y - 270 },
    { x: center.x + 455, y: center.y - 70 },
    { x: center.x - 455, y: center.y - 70 },
    { x: center.x - 92, y: center.y + 285 },
    { x: center.x - 650, y: center.y - 245 },
    { x: center.x + 650, y: center.y + 205 },
    { x: center.x - 650, y: center.y + 225 },
    { x: center.x + 645, y: center.y - 255 },
    { x: center.x - 95, y: center.y - 405 },
  ];
  const satelliteSlots = [
    { x: center.x + 330, y: center.y - 312 },
    { x: center.x + 360, y: center.y + 235 },
    { x: center.x - 330, y: center.y + 330 },
    { x: center.x - 340, y: center.y - 305 },
    { x: center.x + 690, y: center.y - 5 },
    { x: center.x - 705, y: center.y + 0 },
    { x: center.x + 150, y: center.y + 430 },
    { x: center.x - 160, y: center.y - 395 },
  ];
  const place = (node, slot) => {
    const size = graphNodeSize(node);
    let x = slot.x - size.w / 2;
    let y = slot.y - size.h / 2;
    x = clamp(x, 40, 1760 - size.w);
    y = clamp(y, 38, 1080 - size.h);
    for (let tries = 0; tries < 36 && collides(x, y, size, positions); tries++) {
      const angle = (Math.PI * 2 * tries) / 12;
      const push = 20 + tries * 8;
      x = clamp(slot.x - size.w / 2 + Math.cos(angle) * push, 40, 1760 - size.w);
      y = clamp(slot.y - size.h / 2 + Math.sin(angle) * push, 38, 1080 - size.h);
    }
    positions.set(node.id, { x, y, ...size, kind: node.kind });
  };
  people.forEach((node, index) => {
    place(node, personSlots[index] || personSlots[index % personSlots.length]);
  });
  satellites.forEach((node, index) => {
    place(node, satelliteSlots[index] || satelliteSlots[index % satelliteSlots.length]);
  });
  return positions;
}

function graphNodeSize(node) {
  if (node.kind === "summary") return { w: 298, h: 298 };
  if (node.kind === "person") {
    const rank = personRank(node);
    if (rank === "水王") return { w: 292, h: 152 };
    if (rank === "超神") return { w: 280, h: 146 };
    if (rank === "SSS") return { w: 266, h: 140 };
    if (rank === "SS") return { w: 254, h: 134 };
    if (rank === "S") return { w: 244, h: 128 };
    if (rank === "A") return { w: 216, h: 116 };
    if (rank === "B") return { w: 196, h: 106 };
    return { w: 168, h: 96 };
  }
  if (["story", "trait"].includes(node.kind)) return { w: 176, h: 90 };
  if (node.kind === "fact") return { w: 202, h: 92 };
  if (node.kind === "topic") return { w: 184, h: 86 };
  if (node.kind === "object") return { w: 184, h: 86 };
  return { w: 164, h: 82 };
}

function collides(x, y, size, positions) {
  for (const pos of positions.values()) {
    const gap = 30;
    if (x < pos.x + pos.w + gap && x + size.w + gap > pos.x && y < pos.y + pos.h + gap && y + size.h + gap > pos.y) return true;
  }
  return false;
}

function kindWeight(kind) {
  return { summary: 0, person: 1, story: 2, trait: 3, topic: 4, fact: 5, strategy: 6, preference: 7, object: 8, entity: 9 }[kind] ?? 10;
}

function graphNodeTone(node) {
  const meta = node.meta || {};
  const text = `${node.label || ""} ${meta.subject || ""} ${meta.object || ""} ${meta.category || ""}`;
  if (/风险|封号|安全|只读|禁止|异常|冲突/.test(text)) return "risk";
  if (node.kind === "summary") return "core";
  if (node.kind === "person") return `person-tone person-${rankClassName(personRank(node))}`;
  if (node.kind === "fact" || node.kind === "object") return "fact-tone";
  if (node.kind === "topic") return "topic-tone";
  if (node.kind === "story") return "story-tone";
  if (node.kind === "trait" || node.kind === "preference") return "trait-tone";
  return "entity-tone";
}

function nodeLabel(id) {
  return String(id || "").replace(/^(summary|topic|person|fact|object|preference|story|trait):/, "").split(":").filter(Boolean).slice(-1)[0] || id;
}

function filterVisible(node) {
  return true;
}

function updateGraphFilter() {
  document.querySelectorAll("[data-graph-filter]").forEach((button) => button.classList.toggle("on", button.dataset.graphFilter === state.graph.filter));
  const visibleIds = new Set();
  document.querySelectorAll(".graph-node").forEach((node) => {
    const visible = filterVisible({ kind: node.dataset.kind });
    node.classList.toggle("hidden", !visible);
    if (visible) visibleIds.add(node.dataset.id);
    node.classList.toggle("selected", node.dataset.id === state.graph.selectedId);
  });
  document.querySelectorAll(".graph-edges path").forEach((path) => {
    const visible = visibleIds.has(path.dataset.source) && visibleIds.has(path.dataset.target);
    path.classList.toggle("hidden", !visible);
    path.classList.toggle("selected", path.dataset.source === state.graph.selectedId || path.dataset.target === state.graph.selectedId);
  });
  document.querySelectorAll(".leader-row").forEach((row) => {
    row.classList.toggle("selected", row.dataset.leaderNode === state.graph.selectedId);
  });
}

function selectedGraphNode() {
  return state.graph.nodes.find((node) => node.id === state.graph.selectedId) || null;
}

function selectGraphNode(id) {
  state.graph.selectedId = id;
  updateGraphFilter();
  renderGraphDetail(selectedGraphNode());
}

function clearGraphSelection() {
  if (!state.graph.selectedId) return;
  state.graph.selectedId = null;
  updateGraphFilter();
  renderGraphDetail(null);
}

function renderGraphDetail(node) {
  const root = $("graphDetail");
  if (!root) return;
  if (!node) {
    root.innerHTML = `<div class="graph-detail-empty"><strong>点击节点查看详情</strong><span>人物画像、事实、主题和群摘要会在这里分段展开。</span></div>`;
    return;
  }
  const meta = node.meta || {};
  root.innerHTML = `
    <button class="graph-detail-close" type="button" aria-label="关闭">×</button>
    <div class="graph-detail-head">
      <span>${escapeHtml(graphKindName(node.kind))}</span>
      <strong>${escapeHtml(node.label || node.id)}</strong>
      <em>${escapeHtml(detailSubtitle(node))}</em>
    </div>
    ${detailBody(node, meta)}
  `;
  root.querySelector(".graph-detail-close")?.addEventListener("click", (event) => {
    event.stopPropagation();
    clearGraphSelection();
  });
}

function graphKindName(kind) {
  return { summary: "群记忆核心", person: "人物画像", fact: "事件/事实记忆", topic: "群主题", story: "记忆节点", trait: "性格记忆", preference: "偏好记忆", object: "关联事件记忆", entity: "实体记忆" }[kind] || "记忆节点";
}

function detailSubtitle(node) {
  const meta = node.meta || {};
  if (node.kind === "summary") return `${fmtNumber(meta.message_count || node.count || state.memory?.messages || 0)} 条消息 · ${fmtTime(meta.end_time)}`;
  if (node.kind === "person") return `${fmtNumber(meta.message_count || node.count || 0)} 条发言 · ${personRank(node)} 级活跃度`;
  if (node.kind === "fact") return `${meta.category || "事实"} · 置信 ${formatConfidence(meta.confidence)}`;
  return `${node.kind || "node"} · ${fmtNumber(node.count || 0)}`;
}

function detailBody(node, meta) {
  if (node.kind === "summary") {
    const relatedFacts = summaryRelatedFacts(meta);
    return `
      <div class="core-detail-hero detail-card">
        <div class="core-detail-mark" aria-hidden="true"><span></span></div>
        <div>
          <h4>群组核心摘要</h4>
          <p>${escapeHtml(meta.summary || "暂无摘要内容")}</p>
        </div>
      </div>
      ${detailList("主要话题", meta.topics || [])}
      ${detailList("未决问题", meta.open_questions || [])}
      ${factDetailCards(relatedFacts, "核心关联事件")}
      ${detailKpis([
        ["消息量", fmtNumber(meta.message_count || node.count || state.memory?.messages || 0)],
        ["人物", fmtNumber((state.semantic?.people || []).length)],
        ["事实", fmtNumber((state.semantic?.facts || []).length)]
      ])}
    `;
  }
  if (node.kind === "person") {
    const story = uniqueStrings(meta.storyline || []);
    const snippets = uniqueStrings(meta.recent_snippets || meta.evidence || []);
    const traits = flattenDetailValues(meta.traits);
    const preferences = flattenDetailValues(meta.preferences);
    const facts = relatedFactsForPerson(meta);
    const count = Number(meta.message_count || node.count || 0);
    const rank = personRank(node);
    const displayName = node.label || meta.display_name || meta.contact_display_name || meta.person_key || "群成员";
    const username = meta.username || meta.person_key || "";
    const avatar = meta.avatar_url || "";
    return `
      <div class="person-detail-hero">
        <div class="person-hero-avatar rank-${rankClassName(rank)}">${avatar ? `<img src="${escapeAttr(avatar)}" alt="">` : `<span>${escapeHtml(personInitial({ display_name: displayName, person_key: username }))}</span>`}</div>
        <div>
          <strong>${escapeHtml(displayName)}</strong>
          <span>${fmtNumber(count)} 条发言 · ${rank} 级 · ${meta.inferred ? "聊天片段推断" : "长期画像"}${username && username !== displayName ? ` · ${escapeHtml(username)}` : ""}</span>
        </div>
      </div>
      <div class="trend-card detail-card">
        <div class="trend-head"><h4>发言量趋势</h4><span>${escapeHtml(personRankLabel(rank))}</span></div>
        <div class="sparkline" style="--spark-level:${Math.max(24, Math.min(100, count))}%"><i></i></div>
      </div>
      ${detailKpis([
        ["活跃程度", `${rank} 级`],
        ["置信", formatConfidence(meta.confidence)],
        ["最新发言", fmtTime(meta.latest_time)]
      ])}
      <div class="detail-card"><h4>性格总结</h4><p>${escapeHtml(traits[0] || story[0] || "当前画像仍在积累中。")}</p></div>
      ${detailList("偏好记忆", preferences.length ? preferences : traits.slice(1, 4))}
      ${detailTimeline("人物故事线", story)}
      ${detailList("关联事实", facts)}
      ${detailTimeline("最近聊天证据", snippets)}
    `;
  }
  if (node.kind === "fact") {
    return factDetailCards([meta], meta.category === "event" ? "事件记忆详情" : "事件/事实记忆详情");
  }
  if (node.kind === "topic") {
    return `<div class="detail-card"><h4>主题摘要</h4><p>${escapeHtml(meta.summary || "这个话题来自群摘要。")}</p></div><span class="detail-chip">${escapeHtml(meta.topic || node.label)}</span>`;
  }
  if (node.kind === "story") {
    return `<p>${escapeHtml(meta.story || node.label)}</p>`;
  }
  if (node.kind === "trait") {
    return `<p>${escapeHtml(meta.trait || node.label)}</p>`;
  }
  if (node.kind === "object") {
    return factDetailCards(meta.facts || [], "关联事件记忆") || `<p>${escapeHtml(node.label || "暂无更多详情")}</p>`;
  }
  if (node.kind === "preference") {
    return `<p>${escapeHtml(formatObjectValue(meta.value || node.label))}</p>`;
  }
  return `<p>${escapeHtml(graphNodeBody(node) || "暂无更多详情")}</p>`;
}

function summaryRelatedFacts(meta) {
  const facts = state.semantic?.facts || [];
  const chat = meta.chat_username || meta.item_id || "";
  const topics = new Set(meta.topics || []);
  return facts
    .filter((fact) => !chat || !fact.chat_username || fact.chat_username === chat)
    .sort((a, b) => factTimeValue(b) - factTimeValue(a))
    .filter((fact) => fact.category === "event" || topics.has(fact.category) || topics.has(fact.subject))
    .slice(0, 5);
}

function factTimeValue(fact) {
  if (Number(fact?.last_seen_time)) return Number(fact.last_seen_time);
  const parsed = Date.parse(fact?.updated_at || "");
  return Number.isFinite(parsed) ? parsed / 1000 : 0;
}

function factDetailCards(facts, title = "事件记忆") {
  if (!Array.isArray(facts) || !facts.length) return "";
  return `
    <div class="detail-section detail-card">
      <h4>${escapeHtml(title)}</h4>
      <div class="memory-fact-stack">
        ${facts.slice(0, 6).map((fact) => `
          <article class="event-memory-card">
            <div class="event-memory-head">
              <strong>${escapeHtml(fact.subject || "记忆主体")}</strong>
              <span>${escapeHtml(fact.category || "other")} · 置信 ${formatConfidence(fact.confidence)}</span>
            </div>
            <p>${escapeHtml(`${fact.predicate || ""} ${fact.object || ""}`.trim() || fact.object || "暂无内容")}</p>
            <div class="event-memory-meta">
              ${fact.updated_at ? `<span>更新 ${escapeHtml(shortDate(fact.updated_at))}</span>` : ""}
              ${fact.last_seen_time ? `<span>最近 ${escapeHtml(fmtTime(fact.last_seen_time))}</span>` : ""}
              ${fact.fact_id ? `<span>ID ${escapeHtml(String(fact.fact_id).slice(0, 10))}</span>` : ""}
            </div>
            ${sourceMessageList(fact.source_messages || []) || sourceMessageChips(fact.source_message_uids || [])}
          </article>
        `).join("")}
      </div>
    </div>
  `;
}

function sourceMessageChips(items) {
  if (!Array.isArray(items) || !items.length) return "";
  return `<div class="source-chip-row">${uniqueStrings(items).slice(0, 5).map((item) => `<span>${escapeHtml(String(item).slice(0, 12))}</span>`).join("")}</div>`;
}

function sourceMessageList(items) {
  if (!Array.isArray(items) || !items.length) return "";
  return `
    <div class="source-message-list">
      ${items.slice(0, 5).map((item) => `
        <div>
          <strong>${escapeHtml(item.sender_name || item.sender_key || "未知成员")}</strong>
          <span>${escapeHtml(item.text || `[${item.type_label || "消息"}]`)}</span>
          <small>${escapeHtml(fmtTime(item.create_time))}</small>
        </div>
      `).join("")}
    </div>
  `;
}

function detailList(title, items) {
  if (!Array.isArray(items) || !items.length) return "";
  return `<div class="detail-section detail-card"><h4>${escapeHtml(title)}</h4>${uniqueStrings(items).slice(0, 8).map((item) => `<span class="detail-chip">${escapeHtml(item)}</span>`).join("")}</div>`;
}

function detailObject(title, value) {
  const text = formatObjectValue(value);
  if (!text) return "";
  return `<div class="detail-section detail-card"><h4>${escapeHtml(title)}</h4><p>${escapeHtml(text)}</p></div>`;
}

function detailTimeline(title, items) {
  if (!Array.isArray(items) || !items.length) return "";
  return `<div class="detail-section detail-card"><h4>${escapeHtml(title)}</h4><div class="detail-timeline">${uniqueStrings(items).slice(0, 8).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div></div>`;
}

function detailKpis(items) {
  return `<div class="detail-kpis">${items.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "--")}</strong></div>`).join("")}</div>`;
}

function flattenDetailValues(value) {
  if (!value) return [];
  if (Array.isArray(value)) return uniqueStrings(value);
  if (typeof value === "object") {
    const output = [];
    for (const [key, raw] of Object.entries(value)) {
      if (Array.isArray(raw)) output.push(...raw);
      else if (raw && typeof raw === "object") output.push(formatObjectValue(raw));
      else if (raw) output.push(`${key}: ${raw}`);
    }
    return uniqueStrings(output);
  }
  return uniqueStrings([value]);
}

function relatedFactsForPerson(meta) {
  const keys = uniqueStrings([meta.person_key, meta.display_name]).filter(Boolean);
  if (!keys.length) return [];
  const facts = state.semantic?.facts || [];
  return facts
    .filter((fact) => keys.some((key) => [fact.subject, fact.object, fact.predicate].some((field) => String(field || "").includes(key))))
    .map((fact) => `${fact.subject || ""} ${fact.predicate || ""} ${fact.object || ""}`.trim())
    .slice(0, 6);
}

function shortDate(value) {
  if (!value) return "--";
  const text = String(value);
  return text.includes("T") ? text.split("T")[0] : text.slice(0, 16);
}

function fitGraph() {
  const viewport = $("graphViewport");
  if (!viewport) return;
  const rect = viewport.getBoundingClientRect();
  const sidebarWidth = graphSidebarWidth();
  const usableWidth = Math.max(360, rect.width - sidebarWidth);
  const worldWidth = state.graph.worldWidth || 1800;
  const worldHeight = state.graph.worldHeight || 1120;
  state.graph.scale = Math.min(usableWidth / worldWidth, rect.height / worldHeight) * 1.08;
  state.graph.x = sidebarWidth + (usableWidth - worldWidth * state.graph.scale) / 2;
  state.graph.y = (rect.height - worldHeight * state.graph.scale) / 2;
  applyGraphTransform(true);
}

function graphSidebarWidth() {
  const board = $("graphLeaderboard");
  if (!board) return 0;
  const rect = board.getBoundingClientRect();
  return rect.width ? rect.width + 20 : 0;
}

function applyGraphTransform(immediate = false) {
  const apply = () => {
    state.graph.transformFrame = 0;
    $("graphWorld").style.transform = `translate3d(${state.graph.x}px, ${state.graph.y}px, 0) scale(${state.graph.scale})`;
  };
  if (immediate) {
    if (state.graph.transformFrame) cancelAnimationFrame(state.graph.transformFrame);
    apply();
    return;
  }
  if (!state.graph.transformFrame) state.graph.transformFrame = requestAnimationFrame(apply);
}

function zoomGraph(delta) {
  const viewport = $("graphViewport");
  const rect = viewport.getBoundingClientRect();
  const sidebarWidth = graphSidebarWidth();
  const oldScale = state.graph.scale;
  const newScale = clamp(oldScale * delta, 0.35, 2.4);
  const cx = sidebarWidth + (rect.width - sidebarWidth) / 2;
  const cy = rect.height / 2;
  state.graph.x = cx - ((cx - state.graph.x) / oldScale) * newScale;
  state.graph.y = cy - ((cy - state.graph.y) / oldScale) * newScale;
  state.graph.scale = newScale;
  applyGraphTransform(true);
}

async function load() {
  const payload = await fetchJson(statusUrl());
  state.config = payload.config;
  state.memory = payload.memory;
  state.semantic = payload.semantic_memory;
  state.semanticRuns = payload.semantic_runs;
  state.autoReply = payload.auto_reply;
  state.activeProfileId = payload.config.active_llm_profile_id;
  renderProfiles();
  fillProfileForm(activeProfile());
  fillAgent();
  renderTalkModes();
  fillReplySenderForm();
  renderLayers();
  renderLastTest(payload.last_test || {});
  updateTop();
  await Promise.allSettled([loadChats(), loadSuiteStatus()]);
  renderDebugModeOptions();
  renderSemanticRuns();
  renderAutoReplyStatus();
  renderAutoReplyLive();
  renderMemoryChatSelects();
  await loadSkills();
}

async function refreshStatus() {
  const payload = await fetchJson(statusUrl());
  mergeRuntimeStatus(payload);
  updateTop();
  renderProfiles();
  renderSemanticDetails();
  renderSemanticRuns();
  if (state.view === "services") await loadSuiteStatus();
  if (state.view === "chat") await loadChats(true);
  if (state.view === "skills") await loadSkills();
}

async function refreshAutoReplyLive() {
  const payload = await fetchJson("/api/reply/auto-state");
  state.autoReply = payload.auto_reply || state.autoReply;
  renderAutoReplyStatus();
  renderAutoReplyLive();
}

async function loadChats(refreshMessages = false) {
  const [summary, data, types] = await Promise.all([fetchJson("/api/chats/summary"), fetchJson("/api/chats"), fetchJson("/api/chats/types")]);
  state.chatSummary = summary;
  state.chats = data.chats || [];
  state.chatTypes = types.types || [];
  if (state.selectedChat) {
    state.selectedChat = state.chats.find((chat) => chat.username === state.selectedChat.username) || state.selectedChat;
  }
  $("chatSummary").textContent = `${fmtNumber(summary.chats)} 会话 · ${fmtNumber(summary.messages)} 消息`;
  renderTypeFilter();
  renderChatStats();
  renderChatList();
  renderReplyAllowedChats();
  renderMemoryChatSelects();
  if (!state.selectedChat && state.chats.length) await selectChat(state.chats[0].username);
  else if (refreshMessages && state.selectedChat) await loadCurrentMessages();
}

function renderTypeFilter() {
  const select = $("typeFilter");
  if (!select) return;
  const current = select.value;
  select.innerHTML = `<option value="">全部类型</option>` + state.chatTypes
    .map((item) => `<option value="${escapeAttr(item.type)}">${escapeHtml(item.type)} (${fmtNumber(item.count)})</option>`)
    .join("");
  select.value = current;
}

function renderChatStats() {
  const root = $("chatStats");
  if (!root) return;
  const summary = state.chatSummary || {};
  const sync = summary.sync || {};
  const updated = sync.finished_at ? new Date(sync.finished_at).toLocaleString("zh-CN", { hour12: false }) : "--";
  const changed = sync.ingest?.changed_rows ?? 0;
  const mediaReady = sync.media?.stats?.ready ?? 0;
  root.innerHTML = `
    <div class="chat-stat"><strong>${fmtNumber(summary.messages)}</strong><span>消息</span></div>
    <div class="chat-stat"><strong>${fmtNumber(summary.chats)}</strong><span>会话</span></div>
    <div class="chat-stat"><strong>${fmtNumber(mediaReady)}</strong><span>媒体可预览</span></div>
    <div class="chat-stat wide"><strong>${fmtNumber(changed)}</strong><span>本轮变化 · ${escapeHtml(updated)}</span></div>
  `;
}

function renderChatList() {
  const root = $("chatList");
  const term = $("chatSearch").value.trim().toLowerCase();
  const chats = state.chats.filter((chat) => !term || (chat.display_name || chat.username || "").toLowerCase().includes(term));
  root.innerHTML = "";
  for (const chat of chats) {
    const item = document.createElement("div");
    item.className = `chat-item ${state.selectedChat?.username === chat.username ? "active" : ""}`;
    item.dataset.chat = chat.username;
    item.innerHTML = `<strong>${escapeHtml(chat.display_name || chat.username)}</strong><span>${fmtNumber(chat.message_count)} 条 · ${fmtTime(chat.latest_time)}</span>`;
    item.addEventListener("click", () => selectChat(chat.username));
    root.appendChild(item);
  }
  renderChatSelect("debugChat", $("debugChat")?.value || state.selectedChat?.username || "", false);
  renderChatSelect("semanticChat", state.config?.semantic_extract?.chat_username || "", true);
  renderMemoryChatSelects();
}

function renderChatSelect(id, selected = "", includeAll = false, allLabel = "全部会话") {
  const select = $(id);
  if (!select) return;
  const current = selected === undefined || selected === null ? (select.value || "") : String(selected);
  const options = [];
  if (includeAll) options.push(`<option value="">${escapeHtml(allLabel)}</option>`);
  for (const chat of state.chats || []) {
    options.push(`<option value="${escapeAttr(chat.username)}">${escapeHtml(chat.display_name || chat.username)}</option>`);
  }
  select.innerHTML = options.join("");
  if ([...select.options].some((option) => option.value === current)) select.value = current;
}

function renderMemoryChatSelects() {
  renderChatSelect("memoryChat", state.memoryChat, true, "全部记忆");
  renderChatSelect("memoryChatPanel", state.memoryChat, true, "全部记忆");
  const scope = state.semantic?.scope || {};
  const chat = activeMemoryChat();
  const label = state.memoryChat
    ? (chat?.display_name || scope.chat_display_name || state.memoryChat)
    : "全部会话";
  const hint = $("memoryScopeHint");
  if (hint) {
    const count = scope.message_count || chat?.message_count || 0;
    hint.innerHTML = `<i class="legend-core"></i>${escapeHtml(label)}${state.memoryChat ? ` · ${fmtNumber(count)} 条` : ""}`;
  }
}

async function selectChat(username) {
  state.selectedChat = state.chats.find((chat) => chat.username === username) || null;
  renderChatList();
  if (!state.selectedChat) return;
  setMemoryChat(state.selectedChat.username).catch((error) => console.warn(error));
  await loadCurrentMessages();
}

async function loadCurrentMessages() {
  if (!state.selectedChat) return;
  $("activeGroupName").textContent = state.selectedChat.display_name || state.selectedChat.username;
  $("activeGroupMeta").textContent = `${fmtNumber(state.selectedChat.message_count)} 条消息已索引`;
  $("selectedChatName").textContent = state.selectedChat.display_name || state.selectedChat.username;
  $("selectedChatMeta").textContent = `${fmtNumber(state.selectedChat.message_count)} 条 · ${fmtTime(state.selectedChat.latest_time)}`;
  const q = $("messageSearch").value.trim();
  if (q) return searchMessages();
  const params = new URLSearchParams({ chat: state.selectedChat.username, limit: "120" });
  const type = $("typeFilter")?.value || "";
  if (type) params.set("type", type);
  const data = await fetchJson(`/api/chats/messages?${params.toString()}`);
  renderMessages(data.messages || []);
}

async function searchMessages() {
  if (!state.selectedChat) return;
  const q = $("messageSearch").value.trim();
  const type = $("typeFilter")?.value || "";
  if (!q) return selectChat(state.selectedChat.username);
  const params = new URLSearchParams({ chat: state.selectedChat.username, q, limit: "120" });
  if (type) params.set("type", type);
  const data = await fetchJson(`/api/chats/search?${params.toString()}`);
  renderMessages(data.results || []);
}

function renderInlineContent(value, term = "") {
  const token = "\u0000WXEMOJI";
  let index = 0;
  const replacements = [];
  const withTokens = String(value ?? "").replace(/\[([\u4e00-\u9fa5A-Za-z0-9]{1,8})\]/g, (raw, name) => {
    const emoji = WX_EMOJI[name];
    if (!emoji) return raw;
    const id = `${token}${index++}\u0000`;
    replacements.push([id, `<span class="wxEmoji" title="${escapeAttr(raw)}">${emoji}</span>`]);
    return id;
  });
  let html = highlightHtml(withTokens, term);
  for (const [id, replacement] of replacements) html = html.replaceAll(escapeHtml(id), replacement);
  return html;
}

function highlightHtml(value, term = "") {
  const raw = escapeHtml(value);
  if (!term) return raw;
  const safe = String(term).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return raw.replace(new RegExp(safe, "gi"), (match) => `<mark>${match}</mark>`);
}

function renderMessages(messages, term = $("messageSearch")?.value.trim() || "") {
  const root = $("messageList");
  root.innerHTML = "";
  state.lastMessages = messages || [];
  if (!messages.length) return renderEmpty(root, "暂无消息");
  for (const msg of messages) {
    const item = document.createElement("article");
    item.className = `message ${msg.is_outgoing ? "out" : ""}`;
    const media = renderMedia(msg);
    const quote = renderQuote(msg.quote, term);
    const source = msg.source && msg.source !== msg.display_content ? msg.source : "";
    const showBody = !(msg.media_url && ["image", "sticker", "video"].includes(msg.type_label));
    const actions = [];
    if (msg.type_label === "link_or_file") {
      actions.push(`<button class="mini-btn" type="button" data-article-message="${escapeAttr(msg.message_uid || "")}">识别公众号标题</button>`);
    }
    if (msg.quote && ["3", "43", "47"].includes(String(msg.quote.type || ""))) {
      actions.push(`<button class="mini-btn" type="button" data-image-message="${escapeAttr(msg.message_uid || "")}">理解引用图片</button>`);
    }
    if (["image", "sticker"].includes(msg.type_label) && msg.media_status === "ready") {
      actions.push(`<button class="mini-btn" type="button" data-image-message="${escapeAttr(msg.message_uid || "")}">理解图片</button>`);
    }
    const messageActions = actions.length ? `<div class="message-actions">${actions.join("")}</div>` : "";
    item.innerHTML = `
      <div class="message-meta">${escapeHtml(msg.sender_hint || (msg.is_outgoing ? "我" : ""))} · ${fmtTime(msg.create_time)} · ${escapeHtml(msg.semantic_type || msg.type_label || "")}</div>
      ${showBody ? `<div class="message-content">${renderInlineContent(msg.display_content || "", term)}</div>` : ""}
      ${quote}
      ${media}
      ${source ? `<div class="message-source">${renderInlineContent(source, term)}</div>` : ""}
      ${messageActions}
    `;
    root.appendChild(item);
  }
  root.scrollTop = 0;
}

function renderQuote(quote, term = "") {
  if (!quote || (!quote.content && !quote.sender)) return "";
  return `<blockquote class="message-quote"><strong>${escapeHtml(quote.sender || "引用消息")}</strong><span>${renderInlineContent(quote.content || "[引用内容]", term)}</span></blockquote>`;
}

function renderMedia(msg) {
  if (msg.media_url) {
    if (msg.type_label === "video") return `<video src="${escapeAttr(msg.media_url)}" controls></video>`;
    const cls = msg.type_label === "sticker" ? "sticker-media" : "";
    return `<img class="${cls}" src="${escapeAttr(msg.media_url)}" loading="lazy" alt="${escapeAttr(msg.type_label || "media")}">`;
  }
  if (["image", "sticker", "video"].includes(msg.type_label) && msg.media_status && msg.media_status !== "ready") {
    const reason = {
      missing_metadata: "缺少媒体索引",
      missing_file: "本地未缓存",
      decode_failed: "解码失败",
      encrypted_or_unknown: "本地缓存未解开",
      unsupported_hevc: "暂不支持预览",
    }[msg.media_status] || msg.media_status;
    return `<div class="message-media-status">${escapeHtml(reason)}</div>`;
  }
  return "";
}

async function loadSkills() {
  const payload = await fetchJson("/api/skills");
  state.skills = payload;
  if (!state.selectedSkillId || !(payload.skills || []).some((skill) => skill.skill_id === state.selectedSkillId)) {
    state.selectedSkillId = (payload.skills || [])[0]?.skill_id || "";
  }
  renderSkills({ preserveDetail: isSkillConfigEditing() });
  updateTop();
}

function selectedSkill() {
  return (state.skills?.skills || []).find((skill) => skill.skill_id === state.selectedSkillId) || null;
}

function isSkillConfigEditing() {
  return Boolean(state.skillConfigDirty && state.view === "skills");
}

function markSkillConfigDirty() {
  state.skillConfigDirty = true;
}

function renderSkills(options = {}) {
  if (!$("skillGrid")) return;
  const stats = state.skills?.stats || {};
  $("skillInstalled").textContent = fmtNumber(stats.installed || 0);
  $("skillEnabled").textContent = fmtNumber(stats.enabled || 0);
  $("skillRunsToday").textContent = fmtNumber(stats.today_runs || 0);
  $("skillFailedToday").textContent = fmtNumber(stats.failed || 0);
  $("skillListHint").textContent = `${fmtNumber((state.skills?.skills || []).length)} 个技能`;
  renderSkillGrid();
  if (!options.preserveDetail) renderSkillDetail();
  renderSkillTestSelects();
  renderSkillRuns();
}

function renderSkillGrid() {
  const root = $("skillGrid");
  root.innerHTML = "";
  const skills = state.skills?.skills || [];
  if (!skills.length) return renderEmpty(root, "暂无技能");
  for (const skill of skills) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `skill-card ${skill.skill_id === state.selectedSkillId ? "active" : ""} ${skill.enabled ? "enabled" : ""}`;
    const perms = (skill.permissions || []).map((item) => `<span>${escapeHtml(permissionLabel(item))}</span>`).join("");
    card.innerHTML = `
      <div class="skill-card-top">
        <div class="skill-icon">${escapeHtml(skillIcon(skill))}</div>
        <div><strong>${escapeHtml(skill.name || skill.skill_id)}</strong><em>${escapeHtml(skill.skill_type || "skill")}</em></div>
        <i class="${skill.enabled ? "ok" : ""}">${skill.enabled ? "启用" : "禁用"}</i>
      </div>
      <p>${escapeHtml(skill.description || "暂无描述")}</p>
      <div class="skill-perms">${perms}</div>
    `;
    card.addEventListener("click", () => {
      state.selectedSkillId = skill.skill_id;
      state.skillConfigDirty = false;
      renderSkills();
    });
    root.appendChild(card);
  }
}

function skillIcon(skill) {
  if (skill.skill_id === "meme-sender") return "图";
  if (skill.skill_id === "official-account-reader") return "题";
  if (skill.skill_id === "web-search") return "搜";
  if (skill.skill_id === "image-understanding") return "识";
  if (skill.skill_type === "openapi") return "API";
  return "技";
}

function permissionLabel(value) {
  return {
    read_messages: "读消息",
    network: "联网",
    llm: "模型",
    send_text: "发文字",
    send_image: "发图片",
    script_exec: "脚本",
  }[value] || value;
}

function renderSkillDetail() {
  const skill = selectedSkill();
  const root = $("skillDetail");
  if (!skill) {
    $("skillDetailTitle").textContent = "技能详情";
    $("skillDetailState").textContent = "--";
    root.innerHTML = `<p class="muted">选择一个技能查看详情。</p>`;
    return;
  }
  $("skillDetailTitle").textContent = skill.name || skill.skill_id;
  $("skillDetailState").textContent = skill.enabled ? "已启用" : "已禁用";
  $("skillDetailState").className = `pill ${skill.enabled ? "ok" : ""}`;
  const triggers = (skill.triggers || []).map((item) => `<span class="memory-tag topic">${escapeHtml(item)}</span>`).join("");
  const perms = (skill.permissions || []).map((item) => `<span class="memory-tag ${item === "script_exec" ? "risk" : "person"}">${escapeHtml(permissionLabel(item))}</span>`).join("");
  const configHtml = skill.skill_id === "image-understanding" ? renderImageSkillConfig(skill.config || {}) : `
    <section class="skill-detail-section"><h4>配置 JSON</h4><textarea id="skillConfigJson" rows="7">${escapeHtml(JSON.stringify(skill.config || {}, null, 2))}</textarea></section>
  `;
  root.innerHTML = `
    <section class="skill-detail-section"><h4>说明</h4><p>${escapeHtml(skill.description || "暂无描述")}</p></section>
    <section class="skill-detail-section"><h4>触发词</h4><div class="memory-tag-row">${triggers || `<span class="muted">暂无</span>`}</div></section>
    <section class="skill-detail-section"><h4>权限</h4><div class="memory-tag-row">${perms || `<span class="muted">暂无</span>`}</div></section>
    ${configHtml}
    <section class="skill-detail-actions">
      <button class="btn" type="button" data-skill-action="toggle">${skill.enabled ? "禁用技能" : "启用技能"}</button>
      <button class="btn primary" type="button" data-skill-action="save">保存配置</button>
      <button class="btn" type="button" data-skill-action="export">导出</button>
      ${skill.source === "builtin" ? "" : `<button class="btn danger" type="button" data-skill-action="delete">删除</button>`}
    </section>
  `;
}

function renderImageSkillConfig(config) {
  const keyState = config.api_key_configured ? `Key 已配置 · ${escapeHtml(config.api_key_tail || "")}` : "Key 未配置";
  return `
    <section class="skill-detail-section image-skill-config">
      <h4>图片理解模型</h4>
      <div class="form-grid skill-config-grid">
        <label class="switch-label tight"><input id="imageSkillEnabled" type="checkbox" ${config.enabled !== false ? "checked" : ""} /><span>启用图片理解</span></label>
        <label class="switch-label tight"><input id="imageSkillAutoEnabled" type="checkbox" ${config.auto_enabled !== false ? "checked" : ""} /><span>允许自动触发</span></label>
        <label class="switch-label tight"><input id="imageSkillAutoImages" type="checkbox" ${config.auto_analyze_image_messages ? "checked" : ""} /><span>收到图片自动解析</span></label>
        <label class="switch-label tight"><input id="imageSkillUseActive" type="checkbox" ${config.use_active_profile ? "checked" : ""} /><span>复用当前主模型</span></label>
        <label><span>Base URL</span><input id="imageSkillBaseUrl" value="${escapeAttr(config.base_url || "")}" autocomplete="off" placeholder="https://api.example.com/v1 或本地地址" /></label>
        <label><span>模型</span><input id="imageSkillModel" value="${escapeAttr(config.model || "")}" autocomplete="off" placeholder="gpt-4o-mini / qwen-vl / 本地视觉模型" /></label>
        <label><span>API Key</span><input id="imageSkillApiKey" type="password" autocomplete="off" placeholder="${escapeAttr(keyState)}" /></label>
        <label class="switch-label tight"><input id="imageSkillAllowEmptyKey" type="checkbox" ${config.allow_empty_api_key ? "checked" : ""} /><span>本地模型允许空 Key</span></label>
        <label><span>Temperature</span><input id="imageSkillTemperature" type="number" min="0" max="2" step="0.1" value="${escapeAttr(config.temperature ?? 0.2)}" /></label>
        <label><span>输出上限</span><input id="imageSkillMaxTokens" type="number" min="64" max="8192" step="64" value="${escapeAttr(config.max_tokens ?? 700)}" /></label>
        <label><span>超时秒</span><input id="imageSkillTimeout" type="number" min="3" max="180" step="1" value="${escapeAttr(config.timeout_seconds ?? 45)}" /></label>
        <label><span>缓存小时</span><input id="imageSkillCacheHours" type="number" min="0" max="8760" step="1" value="${escapeAttr(config.cache_hours ?? 720)}" /></label>
        <label class="span-2 textarea-label"><span>图片理解提示词</span><textarea id="imageSkillPrompt" rows="6">${escapeHtml(config.prompt || "")}</textarea></label>
      </div>
      <p class="muted">图片模型走 OpenAI-compatible /chat/completions 的 image_url 格式；本地模型可填本地 Base URL 并开启空 Key。</p>
    </section>
    <section class="skill-detail-section compact-json"><h4>配置 JSON</h4><textarea id="skillConfigJson" rows="5">${escapeHtml(JSON.stringify(config || {}, null, 2))}</textarea></section>
  `;
}

function collectImageSkillConfig(fallback = {}) {
  if (!$("imageSkillBaseUrl")) {
    return JSON.parse($("skillConfigJson")?.value || "{}");
  }
  const config = {
    ...fallback,
    enabled: $("imageSkillEnabled").checked,
    auto_enabled: $("imageSkillAutoEnabled").checked,
    auto_analyze_image_messages: $("imageSkillAutoImages").checked,
    use_active_profile: $("imageSkillUseActive").checked,
    base_url: $("imageSkillBaseUrl").value.trim(),
    model: $("imageSkillModel").value.trim(),
    allow_empty_api_key: $("imageSkillAllowEmptyKey").checked,
    temperature: Number($("imageSkillTemperature").value || 0.2),
    max_tokens: Number($("imageSkillMaxTokens").value || 700),
    timeout_seconds: Number($("imageSkillTimeout").value || 45),
    cache_hours: Number($("imageSkillCacheHours").value || 720),
    prompt: $("imageSkillPrompt").value.trim(),
  };
  const key = $("imageSkillApiKey").value.trim();
  if (key) config.api_key = key;
  else if (fallback.api_key_configured) config.api_key_configured = true;
  $("skillConfigJson").value = JSON.stringify(config, null, 2);
  return config;
}

function renderSkillTestSelects() {
  const select = $("skillTestSelect");
  const chatSelect = $("skillTestChat");
  if (!select || !chatSelect) return;
  const currentSkill = select.value || state.selectedSkillId;
  select.innerHTML = (state.skills?.skills || []).map((skill) => `<option value="${escapeAttr(skill.skill_id)}">${escapeHtml(skill.name || skill.skill_id)}</option>`).join("");
  if ([...select.options].some((option) => option.value === currentSkill)) select.value = currentSkill;
  renderChatSelect("skillTestChat", chatSelect.value || state.memoryChat || state.selectedChat?.username || "", false, "选择会话");
  updateSkillUploadVisibility();
}

function updateSkillUploadVisibility() {
  const visible = $("skillTestSelect")?.value === "image-understanding";
  if ($("skillImageUploadLabel")) $("skillImageUploadLabel").hidden = !visible;
}

function renderSkillRuns() {
  const root = $("skillRunList");
  if (!root) return;
  root.innerHTML = "";
  const runs = state.skills?.runs || [];
  if (!runs.length) return renderEmpty(root, "暂无运行日志");
  for (const run of runs) {
    const item = document.createElement("article");
    item.className = `skill-run ${run.status === "failed" ? "failed" : ""}`;
    item.innerHTML = `
      <div><strong>${escapeHtml(run.skill_id)}</strong><span>${escapeHtml(run.status)} · ${escapeHtml(run.created_at || "")}</span></div>
      <p>${escapeHtml(run.error || JSON.stringify(run.output || {}).slice(0, 160))}</p>
    `;
    root.appendChild(item);
  }
}

async function importSkill() {
  const button = $("submitSkillImportBtn");
  button.disabled = true;
  button.textContent = "导入中";
  try {
    const payload = await fetchJson("/api/skills/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_type: $("skillImportType").value,
        name: $("skillImportName").value.trim(),
        content: $("skillImportContent").value,
      }),
    });
    state.selectedSkillId = payload.skill?.skill_id || state.selectedSkillId;
    $("skillImportContent").value = "";
    await loadSkills();
  } catch (error) {
    alert(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "安装导入";
  }
}

async function mutateSkill(action) {
  const skill = selectedSkill();
  if (!skill) return;
  let url = "/api/skills/config";
  let body = { skill_id: skill.skill_id };
  if (action === "toggle") {
    url = "/api/skills/enable";
    body.enabled = !skill.enabled;
    state.skillConfigDirty = false;
  } else if (action === "save") {
    try {
      body.config = skill.skill_id === "image-understanding"
        ? collectImageSkillConfig(skill.config || {})
        : JSON.parse($("skillConfigJson").value || "{}");
    } catch (error) {
      alert(`配置 JSON 不合法：${error.message}`);
      return;
    }
  } else if (action === "export") {
    const payload = await fetchJson("/api/skills/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    $("skillTestOutput").textContent = `导出文件：${payload.filename}\n\nbase64:\n${payload.zip_base64}`;
    return;
  } else if (action === "delete") {
    url = "/api/skills/delete";
    state.skillConfigDirty = false;
  }
  await fetchJson(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (action === "save") state.skillConfigDirty = false;
  await loadSkills();
}

function readImageUploadPayload() {
  const file = $("skillImageUpload")?.files?.[0];
  if (!file) return Promise.resolve(null);
  if (!file.type.startsWith("image/")) return Promise.reject(new Error("请选择图片文件"));
  if (file.size > 8 * 1024 * 1024) return Promise.reject(new Error("图片不能超过 8MB"));
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || "");
      resolve({
        filename: file.name,
        mime_type: file.type || "image/jpeg",
        size: file.size,
        data: dataUrl.includes(",") ? dataUrl.split(",", 2)[1] : dataUrl,
      });
    };
    reader.onerror = () => reject(reader.error || new Error("读取图片失败"));
    reader.readAsDataURL(file);
  });
}

function skillResultForDisplay(result) {
  if (result?.summary) {
    return [
      result.summary,
      "",
      JSON.stringify({
        ok: result.ok,
        cached: result.cached,
        model: result.model,
        message_uid: result.message_uid,
        media_path: result.media_path,
        resolve_method: result.resolve_method,
        llm: result.details?.llm || result.llm || {},
      }, null, 2),
    ].join("\n");
  }
  return JSON.stringify(result, null, 2);
}

async function runSkillTest(send = false) {
  const skillId = $("skillTestSelect").value;
  const chat = state.chats.find((item) => item.username === $("skillTestChat").value) || {};
  const payload = {
    skill_id: skillId,
    send,
    text: $("skillTestInput").value.trim(),
    keyword: $("skillTestInput").value.trim(),
    url: $("skillTestInput").value.trim(),
    message_uid: $("skillTestInput").dataset.messageUid || "",
    chat_username: chat.username || "",
    chat_display_name: chat.display_name || "",
  };
  $("skillTestOutput").textContent = "运行中...";
  try {
    if (skillId === "image-understanding") {
      const upload = await readImageUploadPayload();
      if (upload) {
        payload.image_upload = upload;
        payload.message_uid = "";
      }
    }
    const result = await fetchJson(send ? "/api/skills/run" : "/api/skills/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("skillTestOutput").textContent = skillResultForDisplay(result);
    await loadSkills();
  } catch (error) {
    $("skillTestOutput").textContent = error.message;
  }
}

async function recognizeArticleMessage(messageUid) {
  const msg = (state.lastMessages || []).find((item) => String(item.message_uid || "") === String(messageUid || ""));
  if (!msg) return;
  await loadSkills();
  state.selectedSkillId = "official-account-reader";
  switchView("skills");
  $("skillTestSelect").value = "official-account-reader";
  $("skillTestChat").value = state.selectedChat?.username || msg.chat_username || "";
  $("skillTestInput").value = msg.app_url || msg.source || msg.display_content || "";
  $("skillTestOutput").textContent = "识别公众号标题中...";
  try {
    const result = await fetchJson("/api/skills/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        skill_id: "official-account-reader",
        send: false,
        text: msg.display_content || "",
        url: msg.app_url || "",
        message: msg,
        chat_username: state.selectedChat?.username || msg.chat_username || "",
        chat_display_name: state.selectedChat?.display_name || msg.chat_display_name || "",
        message_uid: msg.message_uid || "",
      }),
    });
    $("skillTestOutput").textContent = JSON.stringify(result, null, 2);
    await loadSkills();
  } catch (error) {
    $("skillTestOutput").textContent = error.message;
  }
}

async function recognizeImageMessage(messageUid) {
  const msg = (state.lastMessages || []).find((item) => String(item.message_uid || "") === String(messageUid || ""));
  if (!msg) return;
  await loadSkills();
  state.selectedSkillId = "image-understanding";
  switchView("skills");
  $("skillTestSelect").value = "image-understanding";
  $("skillTestChat").value = state.selectedChat?.username || msg.chat_username || "";
  const quotedImage = msg.quote && ["3", "43", "47"].includes(String(msg.quote.type || ""));
  $("skillTestInput").value = quotedImage
    ? `理解这张被引用的图片：${msg.quote.content || msg.display_content || "[引用图片]"}`
    : `理解这张图片：${msg.display_content || "[图片]"}`;
  $("skillTestInput").dataset.messageUid = msg.message_uid || "";
  $("skillTestOutput").textContent = "图片理解中...";
  try {
    const result = await fetchJson("/api/skills/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        skill_id: "image-understanding",
        send: false,
        text: $("skillTestInput").value.trim(),
        message_uid: msg.message_uid || "",
        message: msg,
        chat_username: state.selectedChat?.username || msg.chat_username || "",
        chat_display_name: state.selectedChat?.display_name || msg.chat_display_name || "",
      }),
    });
    $("skillTestOutput").textContent = JSON.stringify(result, null, 2);
    await loadSkills();
  } catch (error) {
    $("skillTestOutput").textContent = error.message;
  }
}

async function loadSuiteStatus() {
  const payload = await fetchJson("/api/suite-status");
  state.suite = payload;
  $("suiteGeneratedAt").textContent = payload.generated_at || "--";
  $("navServiceCount").textContent = fmtNumber((payload.services || []).length);
  renderServices(payload.services || []);
  renderOverviewServices();
  updateServiceStat();
}

function renderServices(services) {
  const root = $("serviceGrid");
  root.innerHTML = "";
  renderSuiteOverview();
  for (const service of services) {
    const containerAvailable = service.container?.available !== false;
    const ok = Boolean(service.health?.ok && (!containerAvailable || service.container?.ok));
    const cls = healthClass(service.health);
    const card = document.createElement("article");
    card.className = `service-card ${ok ? "ok" : "bad"}`;
    const meta = [];
    if (service.port) meta.push(`端口 ${service.port}`);
    if (service.health?.latency_ms !== null && service.health?.latency_ms !== undefined) meta.push(`${service.health.latency_ms} ms`);
    if (service.health?.age_seconds !== null && service.health?.age_seconds !== undefined) meta.push(`更新 ${fmtAge(service.health.age_seconds)}`);
    const container = service.container;
    card.innerHTML = `
      <div class="service-top">
        <div><strong>${escapeHtml(service.name || service.id)}</strong><span>${escapeHtml(service.id || "")}</span></div>
        <span class="pill ${cls}">${healthText(service.health)}</span>
      </div>
      <span>${escapeHtml(service.description || "")}</span>
      <div class="container-line">
        <span class="mini-status ${containerClass(container)}">容器 ${escapeHtml(containerText(container))}</span>
        ${container?.restart_count !== undefined ? `<span>重启 ${fmtNumber(container.restart_count)}</span>` : ""}
        ${container?.id ? `<span>${escapeHtml(container.id)}</span>` : ""}
      </div>
      <div class="service-meta">${meta.map((entry) => `<span>${escapeHtml(entry)}</span>`).join("")}</div>
    `;
    root.appendChild(card);
  }
  const okCount = services.filter((item) => item.health?.ok === true).length;
  $("serviceCount").textContent = `${okCount}/${services.length} 正常`;
}

function renderSuiteOverview() {
  const payload = state.suite || {};
  const counts = payload.counts || {};
  const sync = payload.sync || {};
  const ai = payload.ai || {};
  const syncHealth = (payload.services || []).find((item) => item.id === "wechat-memory-sync")?.health;
  const aiHealth = (payload.services || []).find((item) => item.id === "wechat-ai-memory")?.health;
  const overall = $("statusOverall");
  if (overall) {
    overall.classList.toggle("ok", Boolean(payload.ok));
    overall.classList.toggle("bad", !payload.ok);
  }
  $("statusOverallText").textContent = payload.ok ? "全部正常" : "需要处理";
  $("statusMessageCount").textContent = fmtNumber(counts.messages);
  $("statusLatestMessage").textContent = counts.latest_message_time_text ? `最新 ${counts.latest_message_time_text}` : "--";
  $("statusIndexedCount").textContent = fmtNumber(counts.indexed_messages ?? counts.indexed_chunks);
  $("statusAiAge").textContent = aiHealth ? `更新 ${fmtAge(aiHealth.age_seconds)}` : "--";
  $("statusMediaCount").textContent = fmtNumber(counts.media);
  $("statusMediaStatus").textContent = sync.media?.stats ? `${fmtNumber(sync.media.stats.ready)} 个就绪` : "--";
  $("groupCount").textContent = fmtNumber(counts.groups);
  $("statusChatCount").textContent = fmtNumber(counts.chats);
  const gap = Number(counts.messages || 0) - Number(counts.indexed_messages || 0);
  $("indexGap").textContent = Number.isFinite(gap) ? fmtNumber(gap) : "--";
  $("flowState").textContent = payload.ok ? "链路正常" : "链路异常";
  $("syncSummary").textContent = syncHealth ? `${healthText(syncHealth)}，${fmtAge(syncHealth.age_seconds)}` : "--";
  $("viewerSummary").textContent = `${fmtNumber(counts.messages)} 条消息可查看`;
  $("aiSummary").textContent = `${fmtNumber(counts.indexed_messages)} 条消息已索引`;
  $("syncLog").textContent = compactJson(sync);
  $("aiLog").textContent = compactJson(ai.worker || ai.last_run || ai);
  renderContainers(payload.containers || {});
}

function renderContainers(containers) {
  const root = $("containerGrid");
  if (!root) return;
  const order = ["wechat-selkies", "wechat-memory-sync", "wechat-ai-memory", "wechat-agent-console"];
  const entries = Object.values(containers || {}).sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name));
  root.innerHTML = "";
  for (const item of entries) {
    const row = document.createElement("article");
    row.className = "container-row";
    row.innerHTML = `
      <div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.id || "--")}</small></div>
      <div><span class="mini-status ${containerClass(item)}">${escapeHtml(containerText(item))}</span><small>${escapeHtml(item.docker_status_text || "")}</small></div>
      <div><span title="${escapeAttr(item.image || "")}">${escapeHtml(item.image || "--")}</span><small>镜像</small></div>
      <div><span>${escapeHtml(item.started_at || "--")}</span><small>启动时间</small></div>
      <div><span>${fmtNumber(item.restart_count || 0)}</span><small>重启</small></div>
    `;
    root.appendChild(row);
  }
  $("containerCount").textContent = `${entries.filter((item) => item.ok === true).length}/${entries.length} running`;
}

async function saveAll(button, label = "保存") {
  button.disabled = true;
  button.textContent = "保存中";
  try {
    const payload = await fetchJson("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectConfig()),
    });
    state.config = payload.config;
    state.activeProfileId = payload.config.active_llm_profile_id;
    $("apiKey").value = "";
    renderProfiles();
    fillProfileForm(activeProfile());
    fillAgent();
    renderTalkModes();
    fillReplySenderForm();
    updateTop();
    button.textContent = "已保存";
  } catch (error) {
    button.textContent = "保存失败";
    alert(error.message);
  } finally {
    setTimeout(() => {
      button.disabled = false;
      button.textContent = label;
    }, 900);
  }
}

function collectConfig() {
  syncProfileFromForm();
  syncAgentFromForm();
  syncTalkFromForm();
  syncReplySenderFromForm();
  syncLayersFromForm();
  return state.config;
}

function addProfile() {
  syncProfileFromForm();
  const id = `model-${Date.now().toString(36)}`;
  state.config.llm_profiles.push({
    id,
    name: "新模型",
    base_url: "https://api.example.com/v1",
    model: "",
    api_key: "",
    temperature: 0.4,
    context_window: 1000000,
    max_tokens: 512,
    timeout_seconds: 30,
    health_check_enabled: true,
    health_check_interval_seconds: 120,
  });
  state.activeProfileId = id;
  state.config.active_llm_profile_id = id;
  renderProfiles();
  fillProfileForm(activeProfile());
  updateTop();
}

async function fetchModels() {
  syncProfileFromForm();
  $("modelsBtn").disabled = true;
  $("modelsBtn").textContent = "获取中";
  try {
    await fetchJson("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collectConfig()) });
    const payload = await fetchJson("/api/models");
    const datalist = $("modelOptions");
    datalist.innerHTML = "";
    $("modelList").innerHTML = "";
    for (const model of payload.models || []) {
      const option = document.createElement("option");
      option.value = model;
      datalist.appendChild(option);
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "model-chip";
      chip.textContent = model;
      chip.addEventListener("click", () => {
        $("model").value = model;
        syncProfileFromForm();
        updateTop();
      });
      $("modelList").appendChild(chip);
    }
    if (!(payload.models || []).length) $("modelList").innerHTML = `<span class="model-chip">未返回模型列表</span>`;
  } catch (error) {
    $("modelList").innerHTML = `<span class="model-chip">获取失败：${escapeHtml(error.message)}</span>`;
  } finally {
    $("modelsBtn").disabled = false;
    $("modelsBtn").textContent = "获取模型列表";
  }
}

async function checkLLM() {
  await saveAll($("checkBtn"), "立即检测通断");
  $("checkBtn").disabled = true;
  $("checkBtn").textContent = "检测中";
  try {
    const payload = await fetchJson("/api/check-llm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile_id: state.activeProfileId }) });
    activeProfile().health = payload;
    updateTop();
    renderProfiles();
  } catch (error) {
    alert(error.message);
  } finally {
    $("checkBtn").disabled = false;
    $("checkBtn").textContent = "立即检测通断";
  }
}

function renderLastTest(test) {
  if (!test || Object.keys(test).length === 0) {
    $("testState").className = "pill";
    $("testState").textContent = "待测试";
    $("testMeta").textContent = "--";
    $("usageMeta").textContent = "--";
    $("testOutput").textContent = "等待测试";
    return;
  }
  $("testState").className = test.ok ? "pill ok" : "pill bad";
  $("testState").textContent = test.ok ? "连接正常" : "连接失败";
  $("testMeta").textContent = `${test.model || ""} · ${test.elapsed_ms ?? "--"} ms`;
  $("usageMeta").textContent = test.usage?.total_tokens ? `${test.usage.total_tokens} tokens` : test.tested_at || "--";
  $("testOutput").textContent = test.ok ? test.message || "" : JSON.stringify(test.error || test, null, 2);
}

async function testLLM() {
  $("testBtn").disabled = true;
  $("testBtn").textContent = "测试中";
  try {
    await fetchJson("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collectConfig()) });
    const payload = await fetchJson("/api/test-llm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: $("testPrompt").value }) });
    renderLastTest(payload);
  } catch (error) {
    renderLastTest({ ok: false, error: error.message });
  } finally {
    $("testBtn").disabled = false;
    $("testBtn").textContent = "测试模型";
  }
}

async function extractMemory() {
  $("extractMemoryBtn").disabled = true;
  $("extractMemoryBtn").textContent = "抽取中";
  try {
    await fetchJson("/api/extract-memory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat: state.memoryChat || "", limit: 80, batch_size: 5 }),
    });
    const payload = await fetchJson(statusUrl());
    mergeRuntimeStatus(payload);
    renderLayers();
    updateTop();
    $("extractMemoryBtn").textContent = "抽取完成";
  } catch (error) {
    alert(error.message);
    $("extractMemoryBtn").textContent = "抽取失败";
  } finally {
    setTimeout(() => {
      $("extractMemoryBtn").disabled = false;
      $("extractMemoryBtn").textContent = "抽取记忆";
    }, 1200);
  }
}

async function mutateMemory(button) {
  const controls = button.closest("[data-memory-kind][data-memory-id]");
  if (!controls) return;
  const card = button.closest(".memory-card");
  const kind = controls.dataset.memoryKind;
  const id = controls.dataset.memoryId;
  const action = button.dataset.memoryAction || "save";
  const fields = {};
  if (action === "save") {
    card.querySelectorAll("[data-memory-field]").forEach((input) => {
      const field = input.dataset.memoryField;
      let value = input.value;
      if (["preferences", "traits", "topics", "open_questions"].includes(field)) {
        try { value = JSON.parse(value || (field === "preferences" || field === "traits" ? "{}" : "[]")); } catch {}
      }
      fields[field] = value;
    });
  }
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "处理中";
  try {
    const payload = await fetchJson("/api/memory/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, id, action: action === "save" ? "update" : action, fields, chat: state.memoryChat || "" }),
    });
    state.semantic = payload.semantic_memory || state.semantic;
    renderSemanticDetails();
    updateTop();
  } catch (error) {
    alert(error.message);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function collectDebugPayload() {
  return {
    chat: $("debugChat").value || state.selectedChat?.username || "",
    mode: $("debugMode").value || state.config?.agent?.reply_mode || "normal",
    text: $("debugText").value.trim(),
    recent_limit: 18,
    context: { group_auto_reply_enabled: true },
  };
}

function setReplySendState(text, tone = "") {
  const root = $("replySendState");
  if (!root) return;
  root.className = `reply-send-state ${tone}`.trim();
  root.textContent = text || "未创建发送记录";
}

function collectReplySendPayload() {
  const preview = state.preview || {};
  const replyText = (preview.reply || "").trim();
  if (!preview.ok || !replyText) throw new Error("请先生成可用的回复预览");
  const selectedUsername = $("debugChat").value || state.selectedChat?.username || "";
  const previewUsername = preview.chat || preview.message?.chat_username || "";
  const chatUsername = selectedUsername || previewUsername;
  const selectedChat = state.chats.find((chat) => chat.username === chatUsername) || {};
  const samePreviewChat = !previewUsername || previewUsername === chatUsername;
  const chatDisplayName = selectedChat.display_name || (samePreviewChat ? preview.message?.chat_display_name : "") || chatUsername;
  if (!chatDisplayName) throw new Error("缺少目标群名，无法自动切换微信聊天");
  return {
    chat: chatUsername,
    chat_display_name: chatDisplayName,
    message_uid: samePreviewChat ? preview.message?.message_uid || "" : "",
    source_text: samePreviewChat ? preview.text || preview.message?.text || $("debugText").value.trim() : $("debugText").value.trim(),
    reply_text: replyText,
    scoring: preview.scoring || {},
  };
}

function renderDebugResult(payload) {
  state.debug = payload;
  const scoring = payload.scoring || {};
  $("debugScore").textContent = scoring.score ?? "--";
  $("debugDecision").textContent = scoring.decision === "reply" ? "建议接话" : "建议沉默";
  $("debugThreshold").textContent = `${scoring.mode_label || scoring.mode || "--"} · 阈值 ${scoring.threshold ?? "--"}`;
  const root = $("debugHits");
  root.innerHTML = "";
  const items = [...(scoring.hits || []), ...(scoring.suppressions || [])];
  if (!items.length) return renderEmpty(root, "没有命中规则");
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "score-item";
    row.innerHTML = `<div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.kind || item.effect || "规则")}</span></div><span class="score-value">${escapeHtml(item.score ?? item.effect ?? "")}</span>`;
    root.appendChild(row);
  }
}

async function debugTalk() {
  $("debugTalkBtn").disabled = true;
  $("debugTalkBtn").textContent = "分析中";
  try {
    const payload = await fetchJson("/api/debug-talk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectDebugPayload()),
    });
    renderDebugResult(payload);
  } catch (error) {
    alert(error.message);
  } finally {
    $("debugTalkBtn").disabled = false;
    $("debugTalkBtn").textContent = "评分调试";
  }
}

async function previewReply() {
  $("previewReplyBtn").disabled = true;
  $("previewReplyBtn").textContent = "生成中";
  $("replyPreview").textContent = "正在生成候选回复，不会发送到微信...";
  state.preview = null;
  state.lastOutbox = null;
  setReplySendState("正在生成候选回复");
  try {
    const payload = await fetchJson("/api/preview-reply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectDebugPayload()),
    });
    state.preview = payload;
    renderDebugResult(payload);
    const memoryBits = [
      `${fmtNumber(payload.memory?.summaries?.length || 0)} 摘要`,
      `${fmtNumber(payload.memory?.facts?.length || 0)} 事实`,
      `${fmtNumber(payload.memory?.people?.length || 0)} 人物`,
      `${fmtNumber(payload.memory?.vector_memories?.length || 0)} 历史片段`,
    ].join(" · ");
    $("replyPreview").textContent = payload.ok
      ? `${payload.reply || "模型没有返回可用文本"}\n\n---\n建议：${payload.scoring?.decision || "--"} · ${memoryBits} · sent=false`
      : `生成失败：${JSON.stringify(payload.error || payload.llm || payload, null, 2)}`;
    setReplySendState(payload.ok ? "候选回复已生成，尚未粘贴到微信" : "候选回复不可用", payload.ok ? "" : "bad");
  } catch (error) {
    $("replyPreview").textContent = `生成失败：${error.message}`;
    setReplySendState(`生成失败：${error.message}`, "bad");
  } finally {
    $("previewReplyBtn").disabled = false;
    $("previewReplyBtn").textContent = "生成回复预览";
  }
}

async function pushReplyToWechat(send = false) {
  const button = send ? $("sendReplyBtn") : $("draftReplyBtn");
  const original = button.textContent;
  let payload;
  try {
    payload = collectReplySendPayload();
  } catch (error) {
    setReplySendState(error.message, "bad");
    alert(error.message);
    return;
  }
  if (send) {
    const target = payload.chat_display_name || payload.chat || "目标群";
    const ok = confirm(`确认要发送到「${target}」吗？\n\n系统会先在 3000 的微信窗口里切到这个群，随机等待后粘贴并按回车。`);
    if (!ok) return;
  }
  button.disabled = true;
  button.textContent = send ? "发送中" : "粘贴中";
  setReplySendState(send ? `正在切到「${payload.chat_display_name}」并发送...` : `正在切到「${payload.chat_display_name}」并粘贴草稿...`);
  try {
    const result = await fetchJson(send ? "/api/reply/send" : "/api/reply/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.lastOutbox = result.outbox || null;
    const outboxId = result.outbox?.outbox_id ? ` · ${result.outbox.outbox_id.slice(0, 8)}` : "";
    const delayText = replyDelayText(result.details || result.outbox?.details || {});
    setReplySendState(send ? `已发送到「${payload.chat_display_name}」${outboxId}${delayText}` : `已切到「${payload.chat_display_name}」并粘贴草稿${outboxId}${delayText}`, "ok");
  } catch (error) {
    setReplySendState(`${send ? "发送" : "粘贴"}失败：${error.message}`, "bad");
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function renderEmpty(root, text) {
  root.innerHTML = `<div class="empty-state">${escapeHtml(text)}</div>`;
}

function renderTags(tags) {
  if (!Array.isArray(tags) || !tags.length) return "";
  return `<div class="tag-row">${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>`;
}

function formatObjectValue(value) {
  if (Array.isArray(value)) return value.join("、");
  if (value && typeof value === "object") return Object.entries(value).map(([k, v]) => `${k}:${v}`).join("、");
  return value;
}

function formatConfidence(value) {
  const number = Number(value);
  if (Number.isNaN(number)) return "--";
  return number <= 1 ? `${Math.round(number * 100)}%` : String(number);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function bindEvents() {
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  document.querySelectorAll("[data-view-jump]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.viewJump)));
  document.querySelectorAll("[data-graph-filter]").forEach((button) => button.addEventListener("click", () => {
    state.graph.filter = button.dataset.graphFilter;
    updateGraphFilter();
  }));
  $("zoomOutBtn").addEventListener("click", () => zoomGraph(0.82));
  $("zoomInBtn").addEventListener("click", () => zoomGraph(1.22));
  $("zoomResetBtn").addEventListener("click", fitGraph);
  $("graphViewport").addEventListener("wheel", (event) => {
    event.preventDefault();
    zoomGraph(event.deltaY > 0 ? 0.9 : 1.1);
  }, { passive: false });
  $("graphViewport").addEventListener("click", (event) => {
    if (event.target === $("graphViewport") || event.target === $("graphWorld") || event.target === $("graphNodes") || event.target === $("graphEdges")) {
      clearGraphSelection();
    }
  });
  $("graphLeaderboard")?.addEventListener("pointerdown", (event) => event.stopPropagation());
  $("graphLeaderboard")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-leader-node]");
    if (!button) return;
    event.stopPropagation();
    selectGraphNode(button.dataset.leaderNode);
  });
  $("graphViewport").addEventListener("pointerdown", (event) => {
    if (event.target.closest(".graph-node, .graph-leaderboard, .graph-tools")) return;
    state.graph.dragging = true;
    state.graph.dragMoved = false;
    state.graph.dragStartX = event.clientX;
    state.graph.dragStartY = event.clientY;
    state.graph.lastX = event.clientX;
    state.graph.lastY = event.clientY;
    $("graphViewport").setPointerCapture(event.pointerId);
    $("graphViewport").classList.add("dragging");
  });
  $("graphViewport").addEventListener("pointermove", (event) => {
    if (!state.graph.dragging) return;
    if (Math.abs(event.clientX - state.graph.dragStartX) + Math.abs(event.clientY - state.graph.dragStartY) > 4) {
      state.graph.dragMoved = true;
    }
    state.graph.x += event.clientX - state.graph.lastX;
    state.graph.y += event.clientY - state.graph.lastY;
    state.graph.lastX = event.clientX;
    state.graph.lastY = event.clientY;
    applyGraphTransform();
  });
  $("graphViewport").addEventListener("pointerup", (event) => {
    state.graph.dragging = false;
    if ($("graphViewport").hasPointerCapture(event.pointerId)) $("graphViewport").releasePointerCapture(event.pointerId);
    $("graphViewport").classList.remove("dragging");
  });
  $("refreshBtn").addEventListener("click", () => refreshStatus().catch((error) => alert(error.message)));
  $("extractMemoryBtn").addEventListener("click", extractMemory);
  $("memoryChat")?.addEventListener("change", (event) => setMemoryChat(event.target.value).catch((error) => alert(error.message)));
  $("memoryChatPanel")?.addEventListener("change", (event) => setMemoryChat(event.target.value).catch((error) => alert(error.message)));
  $("chatSearch").addEventListener("input", renderChatList);
  $("messageSearchBtn").addEventListener("click", searchMessages);
  $("typeFilter").addEventListener("change", () => {
    if (state.selectedChat) selectChat(state.selectedChat.username);
  });
  $("messageSearch").addEventListener("keydown", (event) => {
  if (event.key === "Enter") searchMessages();
  });
  $("addProfileBtn").addEventListener("click", addProfile);
  $("saveModelsBtn").addEventListener("click", () => saveAll($("saveModelsBtn"), "保存模型"));
  $("savePersonaBtn").addEventListener("click", () => saveAll($("savePersonaBtn"), "保存人格"));
  $("saveTalkBtn").addEventListener("click", () => saveAll($("saveTalkBtn"), "保存接话设置"));
  $("saveAutoReplyBtn")?.addEventListener("click", () => saveAll($("saveAutoReplyBtn"), "保存自动发送"));
  $("saveMemoryBtn").addEventListener("click", () => saveAll($("saveMemoryBtn"), "保存记忆设置"));
  $("modelsBtn").addEventListener("click", fetchModels);
  $("checkBtn").addEventListener("click", checkLLM);
  $("testBtn").addEventListener("click", testLLM);
  $("debugTalkBtn").addEventListener("click", debugTalk);
  $("previewReplyBtn").addEventListener("click", previewReply);
  $("draftReplyBtn").addEventListener("click", () => pushReplyToWechat(false));
  $("sendReplyBtn").addEventListener("click", () => pushReplyToWechat(true));
  $("refreshSkillsBtn")?.addEventListener("click", () => loadSkills().catch((error) => alert(error.message)));
  $("importSkillBtn")?.addEventListener("click", () => $("skillImportContent")?.focus());
  $("submitSkillImportBtn")?.addEventListener("click", importSkill);
  $("testSkillBtn")?.addEventListener("click", () => runSkillTest(false));
  $("runSkillSendBtn")?.addEventListener("click", () => runSkillTest(true));
  $("skillTestSelect")?.addEventListener("change", (event) => {
    state.selectedSkillId = event.target.value;
    state.skillConfigDirty = false;
    if ($("skillTestInput")) $("skillTestInput").dataset.messageUid = "";
    if (event.target.value !== "image-understanding" && $("skillImageUpload")) $("skillImageUpload").value = "";
    updateSkillUploadVisibility();
    renderSkills();
  });
  $("skillDetail")?.addEventListener("input", markSkillConfigDirty);
  $("skillDetail")?.addEventListener("change", markSkillConfigDirty);
  document.addEventListener("click", (event) => {
    const skillAction = event.target.closest("[data-skill-action]");
    if (skillAction) mutateSkill(skillAction.dataset.skillAction).catch((error) => alert(error.message));
  });
  document.querySelectorAll("[data-memory-tab]").forEach((button) => button.addEventListener("click", () => {
    state.memoryUi.tab = button.dataset.memoryTab || "people";
    document.querySelectorAll("[data-memory-tab]").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelectorAll("[data-memory-page]").forEach((page) => page.classList.toggle("active", page.dataset.memoryPage === state.memoryUi.tab));
    renderMemoryConsole();
  }));
  $("memoryPeopleSearch")?.addEventListener("input", renderMemoryConsole);
  $("memoryFactSearch")?.addEventListener("input", renderMemoryConsole);
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-memory-action]");
    if (button) mutateMemory(button);
    const articleButton = event.target.closest("[data-article-message]");
    if (articleButton) recognizeArticleMessage(articleButton.dataset.articleMessage).catch((error) => alert(error.message));
    const imageButton = event.target.closest("[data-image-message]");
    if (imageButton) recognizeImageMessage(imageButton.dataset.imageMessage).catch((error) => alert(error.message));
  });
  window.addEventListener("resize", () => {
    if (state.view === "overview") fitGraph();
  });
}

bindEvents();
switchView("overview");
load().catch((error) => {
  $("testOutput").textContent = error.message;
  $("testState").className = "pill bad";
  $("testState").textContent = "加载失败";
});
setInterval(() => refreshStatus().catch(() => {}), 5000);
setInterval(() => refreshAutoReplyLive().catch(() => {}), 1500);
