const byId = (id) => document.getElementById(id);

const state = {
  apiBase: byId("apiBase").value,
};

function api(path, options = {}) {
  state.apiBase = byId("apiBase").value.trim() || state.apiBase;
  return fetch(`${state.apiBase}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  }).then(async (response) => {
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Request failed: ${response.status}`);
    }
    return response.json();
  });
}

function setWeekStartDefault() {
  const now = new Date();
  const day = now.getDay();
  const diff = (day + 6) % 7;
  now.setDate(now.getDate() - diff);
  byId("weekStart").value = now.toISOString().slice(0, 10);
}

function renderList(containerId, items, render) {
  const container = byId(containerId);
  container.innerHTML = "";
  items.forEach((item) => {
    const div = document.createElement("div");
    div.className = "item";
    div.innerHTML = render(item);
    container.appendChild(div);
  });
}

function renderTasks(tasks) {
  renderList("taskList", tasks, (task) => `
    <strong>${task.title}</strong>
    <div><small>${task.category} · due ${task.deadline} · ${task.estimated_minutes} min · status ${task.status}</small></div>
  `);
}

function renderParsedTasks(tasks) {
  renderList("parsedTasks", tasks, (task) => `
    <strong>${task.title}</strong>
    <div><small>${task.category} · due ${task.deadline} · ${task.estimated_minutes} min</small></div>
  `);
}

function renderScores(scores) {
  const container = byId("scoreSummary");
  container.innerHTML = Object.entries(scores)
    .map(([key, value]) => `<div class="score-pill"><strong>${key}</strong>: ${value}</div>`)
    .join("");
}

function renderAlerts(alerts) {
  renderList("alerts", alerts, (alert) => `<span class="warning">${alert}</span>`);
}

function renderInsights(insights) {
  const rows = [
    `Strongest window: ${insights.strongest_window}`,
    `Consistency risk: ${insights.consistency_risk}`,
    `Overload risk: ${insights.overload_risk}`,
    ...insights.guidance,
  ];
  renderList("insights", rows, (row) => row);
}

function renderWeekPlan(plan) {
  const container = byId("weekPlan");
  const grouped = new Map();
  plan.blocks.forEach((block) => {
    if (!grouped.has(block.day)) grouped.set(block.day, []);
    grouped.get(block.day).push(block);
  });

  container.innerHTML = "";
  grouped.forEach((blocks, day) => {
    const section = document.createElement("section");
    section.className = "day-column";
    section.innerHTML = `<h3>${day}</h3>`;
    blocks.forEach((block) => {
      const item = document.createElement("div");
      item.className = `block ${block.kind}`;
      item.innerHTML = `
        <strong>${block.title}</strong>
        <div><small>${block.start} - ${block.end}</small></div>
        <div><small>${block.reasoning}</small></div>
      `;
      section.appendChild(item);
    });
    container.appendChild(section);
  });
}

async function loadTasks() {
  const tasks = await api("/tasks");
  renderTasks(tasks);
}

async function loadInsights() {
  const insights = await api("/insights");
  renderInsights(insights);
}

async function parseBrainDump() {
  const text = byId("brainDump").value.trim();
  if (!text) return;
  const parsed = await api("/tasks/brain-dump", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  renderParsedTasks(parsed.tasks);
}

function collectPreferences() {
  return {
    sleep_start: byId("sleepStart").value || "23:00:00",
    sleep_end: byId("sleepEnd").value || "07:00:00",
    focus_start: byId("focusStart").value || "09:00:00",
    focus_end: byId("focusEnd").value || "18:00:00",
    max_deep_blocks_per_day: 3,
    break_minutes: 15,
    preferred_block_minutes: Number(byId("blockMinutes").value || 90),
  };
}

async function generatePlan() {
  const payload = {
    week_start: byId("weekStart").value,
    preferences: collectPreferences(),
  };
  const plan = await api("/planner/generate-week", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderScores(plan.score_summary);
  renderAlerts(plan.alerts);
  renderWeekPlan(plan);
}

async function submitCheckin() {
  const payload = {
    energy_level: Number(byId("energy").value),
    stress_level: Number(byId("stress").value),
    confidence_level: Number(byId("confidence").value),
    note: byId("checkinNote").value,
  };
  const insights = await api("/checkins", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderInsights(insights);
}

async function loadSeedPlan() {
  const plan = await api("/demo/seed-plan");
  renderScores(plan.score_summary);
  renderAlerts(plan.alerts);
  renderWeekPlan(plan);
}

function bindEvents() {
  byId("parseDump").addEventListener("click", () => parseBrainDump().catch(handleError));
  byId("generatePlan").addEventListener("click", () => generatePlan().catch(handleError));
  byId("submitCheckin").addEventListener("click", () => submitCheckin().catch(handleError));
  byId("loadSeed").addEventListener("click", () => loadSeedPlan().catch(handleError));
}

function handleError(error) {
  console.error(error);
  alert(`BalanceOS error: ${error.message}`);
}

async function init() {
  setWeekStartDefault();
  bindEvents();
  await Promise.all([loadTasks(), loadInsights()]).catch(handleError);
}

init();
