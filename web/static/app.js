const state = {
  chats: [],
  selectedChat: null,
  summary: null,
  types: [],
  searchTimer: null,
};

const els = {
  summaryText: document.getElementById("summaryText"),
  syncDot: document.getElementById("syncDot"),
  chatFilter: document.getElementById("chatFilter"),
  chatList: document.getElementById("chatList"),
  chatTitle: document.getElementById("chatTitle"),
  chatMeta: document.getElementById("chatMeta"),
  statusPanel: document.getElementById("statusPanel"),
  messageList: document.getElementById("messageList"),
  messageSearch: document.getElementById("messageSearch"),
  typeFilter: document.getElementById("typeFilter"),
  refreshButton: document.getElementById("refreshButton"),
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

async function api(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

function fmtTime(ts) {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fullTime(ts) {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString("zh-CN");
}

function textOf(value) {
  return value == null || value === "" ? "" : String(value);
}

function escapeHtml(value) {
  return textOf(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function highlight(value, term) {
  const raw = escapeHtml(value);
  if (!term) return raw;
  const safe = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return raw.replace(new RegExp(safe, "gi"), (match) => `<mark>${match}</mark>`);
}

function renderInlineContent(value, term) {
  const token = "\u0000WXEMOJI";
  let index = 0;
  const replacements = [];
  const withTokens = textOf(value).replace(/\[([\u4e00-\u9fa5A-Za-z0-9]{1,8})\]/g, (raw, name) => {
    const emoji = WX_EMOJI[name];
    if (!emoji) return raw;
    const id = `${token}${index++}\u0000`;
    replacements.push([id, `<span class="wxEmoji" title="${escapeHtml(raw)}">${emoji}</span>`]);
    return id;
  });
  let html = highlight(withTokens, term);
  for (const [id, replacement] of replacements) {
    html = html.replaceAll(escapeHtml(id), replacement);
  }
  return html;
}

function mediaHtml(msg) {
  if (msg.media_url) {
    const label = msg.type_label === "sticker" ? "表情" : msg.type_label === "video" ? "视频缩略图" : "图片";
    return `
      <figure class="msgMedia ${msg.type_label === "sticker" ? "stickerMedia" : ""}">
        <img src="${escapeHtml(msg.media_url)}" alt="${label}" loading="lazy" />
      </figure>
    `;
  }
  if (["image", "sticker", "video"].includes(msg.type_label) && msg.media_status && msg.media_status !== "ready") {
    const reason = {
      missing_metadata: "缺少媒体索引",
      missing_file: "本地未缓存",
      decode_failed: "解码失败",
      encrypted_or_unknown: "本地缓存未解开",
      unsupported_hevc: "暂不支持预览",
    }[msg.media_status] || msg.media_status;
    return `<div class="msgMediaStatus">${escapeHtml(reason)}</div>`;
  }
  return "";
}

function quoteHtml(quote, term = "") {
  if (!quote || (!quote.content && !quote.sender)) return "";
  return `
    <blockquote class="msgQuote">
      <strong>${escapeHtml(quote.sender || "引用消息")}</strong>
      <span>${renderInlineContent(quote.content || "[引用内容]", term)}</span>
    </blockquote>
  `;
}

function renderSummary() {
  const summary = state.summary || {};
  const sync = summary.sync || {};
  els.summaryText.textContent = `${summary.chats || 0} 会话 · ${summary.messages || 0} 消息`;
  els.syncDot.className = `dot ${sync.ok === true ? "ok" : sync.ok === false ? "bad" : ""}`;

  const updated = sync.finished_at ? new Date(sync.finished_at).toLocaleString("zh-CN") : "-";
  const changed = sync.ingest?.changed_rows ?? 0;
  const mediaReady = sync.media?.stats?.ready ?? 0;
  els.statusPanel.innerHTML = `
    <div class="stat"><strong>${summary.messages || 0}</strong><span>消息</span></div>
    <div class="stat"><strong>${summary.chats || 0}</strong><span>会话</span></div>
    <div class="stat"><strong>${mediaReady}</strong><span>媒体可预览</span></div>
    <div class="stat wide"><strong>${changed}</strong><span>本轮变化 · ${updated}</span></div>
  `;
}

function renderTypes() {
  const current = els.typeFilter.value;
  els.typeFilter.innerHTML = `<option value="">全部类型</option>` + state.types
    .map((item) => `<option value="${escapeHtml(item.type)}">${escapeHtml(item.type)} (${item.count})</option>`)
    .join("");
  els.typeFilter.value = current;
}

function renderChats() {
  const selected = state.selectedChat?.username;
  els.chatList.innerHTML = state.chats.map((chat) => `
    <button class="chatItem ${chat.username === selected ? "active" : ""}" data-chat="${escapeHtml(chat.username)}">
      <span class="chatAvatar">${chat.is_group ? "群" : "聊"}</span>
      <span class="chatMain">
        <span class="chatName">${escapeHtml(chat.display_name || chat.username)}</span>
        <span class="chatSub">${chat.is_group ? "群聊" : "私聊"} · ${chat.message_count || 0} 条</span>
      </span>
      <span class="chatTime">${fmtTime(chat.latest_time || chat.sort_timestamp || chat.last_timestamp)}</span>
    </button>
  `).join("");
}

function renderMessages(messages, term = "") {
  const wasNearTop = els.messageList.scrollTop < 80;
  els.messageList.classList.toggle("empty", messages.length === 0);
  if (!messages.length) {
    els.messageList.innerHTML = `<div class="emptyState">没有匹配的消息</div>`;
    return;
  }
  els.messageList.innerHTML = messages.map((msg) => {
    const body = msg.display_content || msg.message_content || msg.compress_content || `[${msg.type_label || "unknown"}]`;
    const source = msg.source && msg.source !== body ? msg.source : "";
    const sender = msg.sender_hint || (msg.is_outgoing ? "我" : "");
    const media = mediaHtml(msg);
    const quote = quoteHtml(msg.quote, term);
    const showBody = !(msg.media_url && ["image", "sticker", "video"].includes(msg.type_label));
    const direction = msg.is_outgoing ? "outgoing" : "incoming";
    return `
      <article class="msg ${direction}" title="${escapeHtml(msg.type_label)} · local_id ${escapeHtml(msg.local_id)}">
        <div class="msgHeader">
          <span>${escapeHtml(sender)}</span>
          <time>${fullTime(msg.create_time)}</time>
        </div>
        ${showBody ? `<div class="msgBody">${renderInlineContent(body, term)}</div>` : ""}
        ${quote}
        ${media}
        ${source ? `<div class="msgSource">${renderInlineContent(source, term)}</div>` : ""}
      </article>
    `;
  }).join("");
  if (wasNearTop) {
    els.messageList.scrollTop = 0;
  }
}

async function loadSummary() {
  state.summary = await api("/api/summary");
  renderSummary();
}

async function loadTypes() {
  const data = await api("/api/types");
  state.types = data.types || [];
  renderTypes();
}

async function loadChats() {
  const q = encodeURIComponent(els.chatFilter.value.trim());
  const data = await api(`/api/chats${q ? `?q=${q}` : ""}`);
  state.chats = data.chats || [];
  if (!state.selectedChat && state.chats.length) {
    state.selectedChat = state.chats[0];
  } else if (state.selectedChat) {
    state.selectedChat = state.chats.find((chat) => chat.username === state.selectedChat.username) || state.selectedChat;
  }
  renderChats();
}

async function loadMessages() {
  if (!state.selectedChat) return;
  const q = els.messageSearch.value.trim();
  const type = els.typeFilter.value;
  els.chatTitle.textContent = state.selectedChat.display_name || state.selectedChat.username;
  els.chatMeta.textContent = `${state.selectedChat.is_group ? "群聊" : "私聊"} · ${state.selectedChat.message_count || 0} 条 · ${state.selectedChat.username}`;
  if (q) {
    const data = await api(`/api/search?q=${encodeURIComponent(q)}&chat=${encodeURIComponent(state.selectedChat.username)}&limit=120`);
    renderMessages(data.results || [], q);
    return;
  }
  const params = new URLSearchParams({
    chat: state.selectedChat.username,
    limit: "120",
  });
  if (type) params.set("type", type);
  const data = await api(`/api/messages?${params.toString()}`);
  renderMessages(data.messages || []);
}

async function refreshAll() {
  try {
    await Promise.all([loadSummary(), loadTypes(), loadChats()]);
    await loadMessages();
  } catch (err) {
    els.statusPanel.innerHTML = `<div class="stat"><strong>错误</strong><span>${escapeHtml(err.message)}</span></div>`;
    els.syncDot.className = "dot bad";
  }
}

els.chatList.addEventListener("click", (event) => {
  const button = event.target.closest(".chatItem");
  if (!button) return;
  state.selectedChat = state.chats.find((chat) => chat.username === button.dataset.chat);
  renderChats();
  loadMessages();
});

els.chatFilter.addEventListener("input", () => {
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(async () => {
    await loadChats();
    await loadMessages();
  }, 200);
});

els.messageSearch.addEventListener("input", () => {
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(loadMessages, 220);
});

els.typeFilter.addEventListener("change", loadMessages);
els.refreshButton.addEventListener("click", refreshAll);

refreshAll();
setInterval(refreshAll, 5000);
