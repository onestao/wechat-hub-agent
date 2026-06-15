const state = {
  timer: null,
  busy: false,
};

const $ = (id) => document.getElementById(id);

function fmtNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toLocaleString("zh-CN");
}

function fmtAge(seconds) {
  if (seconds === null || seconds === undefined) return "--";
  const value = Number(seconds);
  if (value < 60) return `${Math.round(value)} 秒前`;
  if (value < 3600) return `${Math.round(value / 60)} 分钟前`;
  return `${Math.round(value / 3600)} 小时前`;
}

function healthClass(health) {
  if (!health || health.ok !== true) {
    if (health && health.stale) return "warn";
    return "bad";
  }
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

function renderServices(services) {
  const root = $("services");
  root.innerHTML = "";
  for (const item of services || []) {
    const cls = healthClass(item.health);
    const meta = [];
    if (item.port) meta.push(`端口 ${item.port}`);
    if (item.health?.latency_ms !== null && item.health?.latency_ms !== undefined) {
      meta.push(`${item.health.latency_ms} ms`);
    }
    if (item.health?.age_seconds !== null && item.health?.age_seconds !== undefined) {
      meta.push(`更新 ${fmtAge(item.health.age_seconds)}`);
    }
    const link = item.url ? `<a href="${item.url}" target="_blank" rel="noreferrer">打开</a>` : "";
    const container = item.container;
    const containerCls = containerClass(container);
    const containerLabel = containerText(container);
    const card = document.createElement("article");
    card.className = "service-card";
    card.innerHTML = `
      <div class="service-top">
        <div class="service-name">
          <strong>${item.name}</strong>
          <small>${item.id}</small>
        </div>
        <span class="badge ${cls}">${healthText(item.health)}</span>
      </div>
      <p>${item.description || ""}</p>
      <div class="container-line">
        <span class="mini-pill ${containerCls}">容器 ${containerLabel}</span>
        ${container?.restart_count !== undefined ? `<span>重启 ${container.restart_count}</span>` : ""}
        ${container?.id ? `<span>${container.id}</span>` : ""}
      </div>
      <div class="service-meta">
        ${meta.map((entry) => `<span>${entry}</span>`).join("")}
        ${link}
      </div>
    `;
    root.appendChild(card);
  }
  const okCount = (services || []).filter((item) => item.health?.ok === true).length;
  $("serviceCount").textContent = `${okCount}/${(services || []).length} 正常`;
}

function renderContainers(containers) {
  const root = $("containers");
  root.innerHTML = "";
  const entries = Object.values(containers || {});
  const order = [
    "wechat-selkies",
    "wechat-memory-sync",
    "wechat-ai-memory",
    "wechat-agent-console",
  ];
  entries.sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name));
  for (const item of entries) {
    const cls = containerClass(item);
    const row = document.createElement("article");
    row.className = "container-row";
    row.innerHTML = `
      <div>
        <strong>${item.name}</strong>
        <small>${item.id || "--"}</small>
      </div>
      <div>
        <span class="mini-pill ${cls}">${containerText(item)}</span>
        <small>${item.docker_status_text || ""}</small>
      </div>
      <div>
        <span title="${item.image || ""}">${item.image || "--"}</span>
        <small>镜像</small>
      </div>
      <div>
        <span>${item.started_at || "--"}</span>
        <small>启动时间</small>
      </div>
      <div>
        <span>${fmtNumber(item.restart_count || 0)}</span>
        <small>重启</small>
      </div>
    `;
    root.appendChild(row);
  }
  const okCount = entries.filter((item) => item.ok === true).length;
  $("containerCount").textContent = `${okCount}/${entries.length} running`;
}

function render(payload) {
  const counts = payload.counts || {};
  const sync = payload.sync || {};
  const ai = payload.ai || {};
  const syncHealth = (payload.services || []).find((item) => item.id === "wechat-memory-sync")?.health;
  const aiHealth = (payload.services || []).find((item) => item.id === "wechat-ai-memory")?.health;
  const overallCls = payload.ok ? "ok" : "bad";

  $("overallText").textContent = payload.ok ? "全部正常" : "需要处理";
  $("generatedAt").textContent = payload.generated_at || "--";
  $("messageCount").textContent = fmtNumber(counts.messages);
  $("latestMessage").textContent = counts.latest_message_time_text ? `最新 ${counts.latest_message_time_text}` : "--";
  $("indexedCount").textContent = fmtNumber(counts.indexed_messages ?? counts.indexed_chunks);
  $("aiAge").textContent = aiHealth ? `更新 ${fmtAge(aiHealth.age_seconds)}` : "--";
  $("mediaCount").textContent = fmtNumber(counts.media);
  $("mediaStatus").textContent = sync.media?.stats ? `${fmtNumber(sync.media.stats.ready)} 个就绪` : "--";
  $("groupCount").textContent = fmtNumber(counts.groups);
  $("chatCount").textContent = fmtNumber(counts.chats);

  const gap = Number(counts.messages || 0) - Number(counts.indexed_messages || 0);
  $("indexGap").textContent = Number.isFinite(gap) ? fmtNumber(gap) : "--";
  $("flowState").textContent = payload.ok ? "链路正常" : "链路异常";
  $("syncSummary").textContent = syncHealth ? `${healthText(syncHealth)}，${fmtAge(syncHealth.age_seconds)}` : "--";
  $("viewerSummary").textContent = `${fmtNumber(counts.messages)} 条消息可查看`;
  $("aiSummary").textContent = `${fmtNumber(counts.indexed_messages)} 条消息已索引`;
  $("syncLog").textContent = compactJson(sync);
  $("aiLog").textContent = compactJson(ai.worker || ai.last_run || ai);

  const mainStatus = document.querySelector(".main-status");
  mainStatus.classList.remove("ok", "warn", "bad");
  mainStatus.classList.add(overallCls);
  renderServices(payload.services || []);
  renderContainers(payload.containers || {});
}

async function refresh() {
  if (state.busy) return;
  state.busy = true;
  $("refreshState").textContent = "刷新中";
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    render(payload);
    $("refreshState").textContent = `已刷新 ${new Date().toLocaleTimeString("zh-CN")}`;
  } catch (error) {
    $("overallText").textContent = "面板异常";
    $("generatedAt").textContent = String(error.message || error);
    document.querySelector(".main-status").classList.remove("ok", "warn");
    document.querySelector(".main-status").classList.add("bad");
    $("refreshState").textContent = "刷新失败";
  } finally {
    state.busy = false;
  }
}

$("refreshBtn").addEventListener("click", refresh);
refresh();
state.timer = window.setInterval(refresh, 5000);
