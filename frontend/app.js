const byId = (id) => document.getElementById(id);

const DEFAULT_VIEW = "overview";
const DAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const state = {
  apiBase: byId("apiBase").value,
  profileId: byId("profileId").value,
  strategies: [],
  tasks: [],
  canvasCourses: [],
  googleCalendars: [],
  activeView: DEFAULT_VIEW,
};

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character] || character;
  });
}

function formatLabel(value) {
  return String(value)
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatTimeLabel(value) {
  return String(value).slice(0, 5);
}

function formatDateTimeLabel(value) {
  if (!value) {
    return "Not synced yet";
  }
  return new Date(value).toLocaleString();
}

function parseIsoDate(value) {
  const [year, month, day] = String(value).split("-").map(Number);
  return new Date(year, month - 1, day);
}

function daysUntil(deadline) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = parseIsoDate(deadline);
  target.setHours(0, 0, 0, 0);
  return Math.round((target - today) / 86400000);
}

function requestedView() {
  const view = window.location.hash.replace(/^#/, "").trim();
  return view || DEFAULT_VIEW;
}

function setActiveView(viewName, syncHash = true) {
  const views = Array.from(document.querySelectorAll("[data-view]")).map((element) => element.dataset.view);
  const nextView = views.includes(viewName) ? viewName : DEFAULT_VIEW;
  state.activeView = nextView;

  document.querySelectorAll("[data-view]").forEach((section) => {
    section.classList.toggle("active", section.dataset.view === nextView);
  });

  document.querySelectorAll("[data-route-link]").forEach((link) => {
    link.classList.toggle("active", link.dataset.routeLink === nextView);
  });

  if (syncHash) {
    history.replaceState(null, "", `#${nextView}`);
  }
}

function api(path, options = {}) {
  state.apiBase = (byId("apiBase").value.trim() || state.apiBase).replace(/\/$/, "");
  state.profileId = (byId("profileId").value.trim() || state.profileId || "demo-user");
  return fetch(`${state.apiBase}${path}`, {
    headers: {
      "Content-Type": "application/json",
      "X-Profile-Id": state.profileId,
    },
    ...options,
  }).then(async (response) => {
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Request failed: ${response.status}`);
    }
    if (response.status === 204) {
      return null;
    }
    return response.json();
  });
}

function renderPreferences(preferences) {
  byId("sleepStart").value = formatTimeLabel(preferences.sleep_start);
  byId("sleepEnd").value = formatTimeLabel(preferences.sleep_end);
  byId("focusStart").value = formatTimeLabel(preferences.focus_start);
  byId("focusEnd").value = formatTimeLabel(preferences.focus_end);
  byId("breakMinutes").value = preferences.break_minutes;
  byId("maxDeepBlocks").value = preferences.max_deep_blocks_per_day;
  byId("blockMinutes").value = preferences.preferred_block_minutes;
}

function setWeekStartDefault() {
  const now = new Date();
  const day = now.getDay();
  const diff = (day + 6) % 7;
  now.setDate(now.getDate() - diff);
  byId("weekStart").value = now.toISOString().slice(0, 10);
}

function setPlanBadge(message, tone = "neutral") {
  const badge = byId("planBadge");
  badge.textContent = message;
  badge.dataset.tone = tone;
}

function renderList(containerId, items, render, emptyMessage = "Nothing to show yet.") {
  const container = byId(containerId);
  container.innerHTML = "";

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "item empty-item";
    empty.textContent = emptyMessage;
    container.appendChild(empty);
    return;
  }

  items.forEach((item) => {
    const div = document.createElement("div");
    div.className = "item";
    div.innerHTML = render(item);
    container.appendChild(div);
  });
}

function renderTaskStats(tasks) {
  const stats = [
    ["Total Tasks", tasks.length],
    ["Pending", tasks.filter((task) => task.status === "pending").length],
    ["Delayed", tasks.filter((task) => task.status === "delayed").length],
    ["Completed", tasks.filter((task) => task.status === "completed").length],
    [
      "Due Soon",
      tasks.filter((task) => task.status !== "completed" && daysUntil(task.deadline) <= 2).length,
    ],
  ];

  byId("taskStats").innerHTML = stats
    .map(
      ([label, value]) => `
        <div class="stat-card">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `
    )
    .join("");
}

function populateStrategySelects(strategies) {
  const selects = [byId("strategySelect"), byId("repairStrategy")];
  selects.forEach((select) => {
    const previousValue = select.value;
    select.innerHTML = "";

    strategies.forEach((strategy) => {
      const option = document.createElement("option");
      option.value = strategy;
      option.textContent = formatLabel(strategy);
      select.appendChild(option);
    });

    if (previousValue && strategies.includes(previousValue)) {
      select.value = previousValue;
    }
  });
}

function populateRepairTasks(tasks) {
  const select = byId("repairTask");
  const activeTasks = tasks.filter((task) => task.status !== "completed");
  const previousValue = select.value;
  select.innerHTML = "";

  if (!activeTasks.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No active tasks available";
    select.appendChild(option);
    select.disabled = true;
    return;
  }

  select.disabled = false;
  activeTasks.forEach((task) => {
    const option = document.createElement("option");
    option.value = task.id;
    option.textContent = `${task.title} (${formatLabel(task.status)})`;
    select.appendChild(option);
  });

  if (previousValue && activeTasks.some((task) => task.id === previousValue)) {
    select.value = previousValue;
  }
}

function renderTasks(tasks) {
  state.tasks = tasks;
  populateRepairTasks(tasks);
  renderTaskStats(tasks);
  renderList(
    "taskList",
    tasks,
    (task) => `
      <div class="task-row">
        <div>
          <strong>${escapeHtml(task.title)}</strong>
          <div class="task-meta">
            <small>${escapeHtml(formatLabel(task.category))} &middot; due ${escapeHtml(task.deadline)} &middot; ${escapeHtml(task.estimated_minutes)} min</small>
          </div>
        </div>
        <span class="status-pill ${escapeHtml(task.status)}">${escapeHtml(formatLabel(task.status))}</span>
      </div>
    `,
    "No tasks available in the store yet."
  );
}

function renderParsedTasks(tasks) {
  renderList(
    "parsedTasks",
    tasks,
    (task) => `
      <strong>${escapeHtml(task.title)}</strong>
      <div class="task-meta">
        <small>${escapeHtml(formatLabel(task.category))} &middot; due ${escapeHtml(task.deadline)} &middot; ${escapeHtml(task.estimated_minutes)} min</small>
      </div>
    `,
    "Parse a brain dump to preview structured tasks."
  );
}

function renderCommitments(commitments) {
  renderList(
    "commitmentList",
    commitments,
    (commitment) => `
      <div class="task-row">
        <div>
          <strong>${escapeHtml(commitment.title)}</strong>
          <div class="task-meta">
            <small>${escapeHtml(DAY_LABELS[commitment.day_of_week])} &middot; ${escapeHtml(formatTimeLabel(commitment.start))}-${escapeHtml(formatTimeLabel(commitment.end))} &middot; ${escapeHtml(formatLabel(commitment.kind))}</small>
          </div>
          ${commitment.location ? `<div class="task-meta"><small>${escapeHtml(commitment.location)}</small></div>` : ""}
        </div>
        <button type="button" class="secondary compact-button" data-delete-commitment="${escapeHtml(commitment.id)}">Remove</button>
      </div>
    `,
    "No fixed commitments yet. Add classes or recurring weekly obligations here."
  );
}

function renderGoogleStatus(status) {
  const container = byId("googleConnectionStatus");
  const tone = !status.configured ? "warning" : status.connected ? "good" : "neutral";
  container.className = `integration-status ${tone}`;

  if (!status.configured) {
    container.innerHTML = `
      <strong>Google Calendar is not configured.</strong>
      <div class="task-meta"><small>${escapeHtml(status.message || "Add Google OAuth env vars on the backend first.")}</small></div>
    `;
    renderGoogleCalendars([]);
    return;
  }

  if (!status.connected) {
    container.innerHTML = `
      <strong>Google Calendar is ready to connect.</strong>
      <div class="task-meta"><small>${escapeHtml(status.message || "Connect this student profile to Google Calendar.")}</small></div>
    `;
    renderGoogleCalendars([]);
    return;
  }

  container.innerHTML = `
    <strong>Connected as ${escapeHtml(status.connected_email || "Google user")}</strong>
    <div class="task-meta"><small>Last sync: ${escapeHtml(formatDateTimeLabel(status.last_synced_at))}</small></div>
  `;
}

function renderGoogleCalendars(calendars) {
  state.googleCalendars = calendars;
  const select = byId("googleCalendarSelect");
  const previousValue = select.value;
  select.innerHTML = "";

  const items = calendars.length
    ? calendars
    : [{ id: "primary", summary: "Primary Calendar", primary: true }];

  items.forEach((calendar) => {
    const option = document.createElement("option");
    option.value = calendar.id;
    option.textContent = calendar.primary ? `${calendar.summary} (Primary)` : calendar.summary;
    select.appendChild(option);
  });

  if (previousValue && items.some((calendar) => calendar.id === previousValue)) {
    select.value = previousValue;
  }
}

function renderGoogleImportSummary(summary) {
  const rows = summary
    ? [
        `Calendar: ${summary.calendar_id}`,
        `Imported commitments: ${summary.imported_commitments}`,
        `Updated commitments: ${summary.updated_commitments}`,
        `Skipped events: ${summary.skipped_events}`,
        summary.message,
        ...summary.imported_titles.map((title) => `Imported: ${title}`),
      ]
    : [];
  renderList(
    "googleImportSummary",
    rows,
    (row) => escapeHtml(row),
    "No Google Calendar import has been run for this profile yet."
  );
}

function renderCanvasStatus(status) {
  const container = byId("canvasConnectionStatus");
  const tone = status.connected ? "good" : "neutral";
  container.className = `integration-status ${tone}`;

  if (!status.connected) {
    container.innerHTML = `
      <strong>Canvas is ready to connect.</strong>
      <div class="task-meta"><small>${escapeHtml(status.message || "Paste your Canvas base URL and personal access token.")}</small></div>
    `;
    renderCanvasCourses([]);
    return;
  }

  container.innerHTML = `
    <strong>Connected to ${escapeHtml(status.base_url || "Canvas")}</strong>
    <div class="task-meta"><small>Last sync: ${escapeHtml(formatDateTimeLabel(status.last_synced_at))}</small></div>
  `;
}

function renderCanvasCourses(courses) {
  state.canvasCourses = courses;
  const select = byId("canvasCourseSelect");
  const previousValue = select.value;
  select.innerHTML = "";

  if (!courses.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Connect Canvas first";
    select.appendChild(option);
    select.disabled = true;
    return;
  }

  select.disabled = false;
  courses.forEach((course) => {
    const option = document.createElement("option");
    option.value = String(course.id);
    option.textContent = course.course_code ? `${course.name} (${course.course_code})` : course.name;
    option.dataset.courseName = course.name;
    select.appendChild(option);
  });

  if (previousValue && courses.some((course) => String(course.id) === previousValue)) {
    select.value = previousValue;
  }
}

function renderCanvasImportSummary(summary) {
  const rows = summary
    ? [
        `Course: ${summary.course_name}`,
        `Imported tasks: ${summary.imported_tasks}`,
        `Updated tasks: ${summary.updated_tasks}`,
        `Skipped assignments: ${summary.skipped_assignments}`,
        summary.message,
        ...summary.imported_titles.map((title) => `Imported: ${title}`),
      ]
    : [];
  renderList(
    "canvasImportSummary",
    rows,
    (row) => escapeHtml(row),
    "No Canvas import has been run for this profile yet."
  );
}

function renderScores(scores = {}) {
  const container = byId("scoreSummary");
  const entries = Object.entries(scores);
  container.innerHTML = entries.length
    ? entries
        .map(
          ([key, value]) => `
            <div class="score-pill">
              <span>${escapeHtml(formatLabel(key))}</span>
              <strong>${escapeHtml(value)}</strong>
            </div>
          `
        )
        .join("")
    : '<div class="score-pill muted-pill">Generate a plan to see goal progress, consistency, and balance.</div>';
}

function renderMetrics(metrics) {
  const container = byId("planMetrics");
  if (!metrics) {
    container.innerHTML = '<div class="metric-card">No plan metrics yet.</div>';
    return;
  }

  const fields = [
    ["scheduled_tasks", "Scheduled Tasks"],
    ["unscheduled_tasks", "Unscheduled Tasks"],
    ["preserved_blocks", "Preserved Blocks"],
    ["schedule_stability_pct", "Stability %"],
    ["overload_days", "Overload Days"],
    ["focus_alignment_pct", "Focus Alignment %"],
  ];

  container.innerHTML = fields
    .map(
      ([key, label]) => `
        <div class="metric-card">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(metrics[key])}</strong>
        </div>
      `
    )
    .join("");
}

function renderAlerts(alerts) {
  renderList(
    "alerts",
    alerts,
    (alert) => `<span class="warning">${escapeHtml(alert)}</span>`,
    "No alerts. The planner has not generated a week yet."
  );
}

function renderInsights(insights) {
  const rows = [
    `Strongest window: ${insights.strongest_window}`,
    `Consistency risk: ${insights.consistency_risk}`,
    `Overload risk: ${insights.overload_risk}`,
    ...insights.guidance,
  ];
  renderList("insights", rows, (row) => escapeHtml(row), "Submit a check-in to generate insights.");
}

function renderWeekPlan(plan) {
  const container = byId("weekPlan");
  const grouped = new Map();
  plan.blocks.forEach((block) => {
    if (!grouped.has(block.day)) grouped.set(block.day, []);
    grouped.get(block.day).push(block);
  });

  container.classList.remove("empty-state");
  container.innerHTML = "";

  if (!grouped.size) {
    container.classList.add("empty-state");
    container.textContent = "This plan has no schedule blocks.";
    return;
  }

  grouped.forEach((blocks, day) => {
    const section = document.createElement("section");
    section.className = "day-column";
    section.innerHTML = `<h3>${escapeHtml(day)}</h3>`;

    blocks.forEach((block) => {
      const item = document.createElement("div");
      item.className = `block ${block.kind}`;
      item.innerHTML = `
        <strong>${escapeHtml(block.title)}</strong>
        <div><small>${escapeHtml(block.start)} - ${escapeHtml(block.end)}</small></div>
        <div><small>${escapeHtml(block.reasoning)}</small></div>
      `;
      section.appendChild(item);
    });

    container.appendChild(section);
  });
}

function renderPlan(plan, badgeMessage, tone = "good") {
  renderScores(plan.score_summary);
  renderMetrics(plan.metrics);
  renderAlerts(plan.alerts);
  renderWeekPlan(plan);
  setPlanBadge(badgeMessage, tone);
}

function renderRepairSummary(payload, mode) {
  const rows = [];
  const plan = mode === "rl" ? payload.result : payload;

  if (mode === "rl" && payload.chosen_strategy && payload.encoded_state) {
    rows.push(`Learned selector chose: ${formatLabel(payload.chosen_strategy)}`);
    rows.push(`Encoded repair state: ${payload.encoded_state.join(" / ")}`);
  }

  if (plan && plan.strategy_used) {
    rows.push(`Plan strategy used: ${formatLabel(plan.strategy_used)}`);
  }

  if (plan && plan.metrics) {
    rows.push(`Scheduled tasks: ${plan.metrics.scheduled_tasks}`);
    rows.push(`Preserved blocks: ${plan.metrics.preserved_blocks}`);
    rows.push(`Overload days: ${plan.metrics.overload_days}`);
    rows.push(`Focus alignment: ${plan.metrics.focus_alignment_pct}%`);
  }

  renderList("repairSummary", rows, (row) => escapeHtml(row), "Run a repair action to inspect the result.");
}

function renderSelectorSummary(summary) {
  const rows = [
    `Episodes: ${summary.episodes}`,
    `Unique states: ${summary.unique_states}`,
    `Average reward: ${summary.average_reward}`,
    `Final epsilon: ${summary.final_epsilon}`,
    ...Object.entries(summary.action_counts || {}).map(
      ([strategy, count]) => `${formatLabel(strategy)} selected ${count} times during training`
    ),
  ];
  renderList("selectorSummary", rows, (row) => escapeHtml(row), "Train the repair selector to see the policy summary.");
}

function collectPreferences() {
  return {
    sleep_start: byId("sleepStart").value || "23:00:00",
    sleep_end: byId("sleepEnd").value || "07:00:00",
    focus_start: byId("focusStart").value || "09:00:00",
    focus_end: byId("focusEnd").value || "18:00:00",
    max_deep_blocks_per_day: Number(byId("maxDeepBlocks").value || 3),
    break_minutes: Number(byId("breakMinutes").value || 15),
    preferred_block_minutes: Number(byId("blockMinutes").value || 90),
  };
}

function collectWeekStart() {
  const weekStart = byId("weekStart").value;
  if (!weekStart) {
    throw new Error("Week start is required.");
  }
  return weekStart;
}

function collectRepairPayload(includeStrategy = true) {
  const taskId = byId("repairTask").value;
  if (!taskId) {
    throw new Error("Choose a task to delay before running repair.");
  }

  const payload = {
    task_id: taskId,
    week_start: collectWeekStart(),
    reason: byId("repairReason").value.trim() || "Task slipped.",
  };

  if (includeStrategy) {
    payload.strategy = byId("repairStrategy").value || undefined;
  }

  return payload;
}

function collectCommitmentPayload() {
  const title = byId("commitmentTitle").value.trim();
  if (!title) {
    throw new Error("Commitment title is required.");
  }

  return {
    title,
    kind: byId("commitmentKind").value,
    day_of_week: Number(byId("commitmentDay").value),
    start: `${byId("commitmentStart").value || "10:00"}:00`,
    end: `${byId("commitmentEnd").value || "11:15"}:00`,
    location: byId("commitmentLocation").value.trim(),
    notes: "",
  };
}

async function loadTasks() {
  const tasks = await api("/tasks");
  renderTasks(tasks);
}

async function loadInsights() {
  const insights = await api("/insights");
  renderInsights(insights);
}

async function loadStrategies() {
  const payload = await api("/planner/strategies");
  state.strategies = payload.strategies || [];
  populateStrategySelects(state.strategies);
}

async function loadPreferences() {
  const preferences = await api("/preferences");
  renderPreferences(preferences);
}

async function loadCommitments() {
  const commitments = await api("/commitments");
  renderCommitments(commitments);
}

async function loadGoogleStatus() {
  const status = await api("/integrations/google/status");
  renderGoogleStatus(status);
  if (status.configured && status.connected) {
    const calendars = await api("/integrations/google/calendars");
    renderGoogleCalendars(calendars);
  }
}

async function loadCanvasStatus() {
  const status = await api("/integrations/canvas/status");
  renderCanvasStatus(status);
  byId("canvasBaseUrl").value = status.base_url || byId("canvasBaseUrl").value;
  if (status.connected) {
    const courses = await api("/integrations/canvas/courses");
    renderCanvasCourses(courses);
  }
}

async function loadProfileData() {
  await Promise.all([
    loadTasks(),
    loadInsights(),
    loadCommitments(),
    loadPreferences(),
    loadGoogleStatus(),
    loadCanvasStatus(),
  ]);
}

async function parseBrainDump() {
  const text = byId("brainDump").value.trim();
  if (!text) return;
  const parsed = await api("/tasks/brain-dump", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  renderParsedTasks(parsed.tasks);
  setActiveView("intake");
}

async function generatePlan() {
  const payload = {
    week_start: collectWeekStart(),
    preferences: collectPreferences(),
    strategy: byId("strategySelect").value || "stability_aware",
  };
  const plan = await api("/planner/generate-week", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderPlan(plan, `Generated with ${formatLabel(plan.strategy_used)}`, "good");
  setActiveView("planner");
}

async function replanWithStrategy() {
  const plan = await api("/planner/replan", {
    method: "POST",
    body: JSON.stringify(collectRepairPayload(true)),
  });
  renderPlan(plan, `Replanned with ${formatLabel(plan.strategy_used)}`, "warning");
  renderRepairSummary(plan, "strategy");
  await loadTasks();
  setActiveView("repair");
}

async function replanWithRL() {
  const payload = collectRepairPayload(false);
  const result = await api("/planner/replan-rl", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderPlan(result.result, `RL selected ${formatLabel(result.chosen_strategy)}`, "accent");
  renderRepairSummary(result, "rl");
  await loadTasks();
  setActiveView("repair");
}

async function trainSelector() {
  const payload = {
    episodes: Number(byId("trainEpisodes").value || 60),
    seed: Number(byId("trainSeed").value || 11),
  };
  const summary = await api("/ml/train-repair-selector", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderSelectorSummary(summary);
  setActiveView("repair");
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
  setActiveView("insights");
}

async function loadSeedPlan() {
  const plan = await api("/demo/seed-plan");
  renderPlan(plan, "Loaded demo seed plan", "neutral");
  await loadTasks();
  setActiveView("planner");
}

async function addCommitment() {
  await api("/commitments", {
    method: "POST",
    body: JSON.stringify(collectCommitmentPayload()),
  });
  byId("commitmentTitle").value = "";
  byId("commitmentLocation").value = "";
  await loadCommitments();
  setActiveView("planner");
}

async function deleteCommitment(commitmentId) {
  await api(`/commitments/${commitmentId}`, { method: "DELETE" });
  await loadCommitments();
}

async function connectGoogleCalendar() {
  const payload = await api("/integrations/google/start");
  const popup = window.open(payload.authorization_url, "_blank", "noopener,noreferrer");
  if (!popup) {
    window.location.href = payload.authorization_url;
  }
}

async function disconnectGoogleCalendar() {
  await api("/integrations/google/connection", { method: "DELETE" });
  renderGoogleImportSummary(null);
  await loadGoogleStatus();
}

async function importGoogleCommitments() {
  const payload = {
    calendar_id: byId("googleCalendarSelect").value || "primary",
    lookahead_days: Number(byId("googleLookaheadDays").value || 28),
  };
  const summary = await api("/integrations/google/import-commitments", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderGoogleImportSummary(summary);
  await Promise.all([loadCommitments(), loadGoogleStatus()]);
  setActiveView("planner");
}

async function connectCanvas() {
  const payload = {
    base_url: byId("canvasBaseUrl").value.trim(),
    access_token: byId("canvasAccessToken").value.trim(),
  };
  await api("/integrations/canvas/connection", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  byId("canvasAccessToken").value = "";
  await loadCanvasStatus();
}

async function disconnectCanvas() {
  await api("/integrations/canvas/connection", { method: "DELETE" });
  renderCanvasImportSummary(null);
  renderCanvasCourses([]);
  await loadCanvasStatus();
}

async function importCanvasAssignments() {
  const courseSelect = byId("canvasCourseSelect");
  const option = courseSelect.selectedOptions[0];
  const courseId = Number(courseSelect.value);
  if (!courseId) {
    throw new Error("Choose a Canvas course before importing assignments.");
  }

  const payload = {
    course_id: courseId,
    course_name: option?.dataset?.courseName || option?.textContent || "",
    default_estimated_minutes: Number(byId("canvasDefaultMinutes").value || 90),
    default_difficulty: 3,
  };
  const summary = await api("/integrations/canvas/import-assignments", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderCanvasImportSummary(summary);
  await Promise.all([loadTasks(), loadCanvasStatus()]);
  setActiveView("tasks");
}

function bindRoutes() {
  document.querySelectorAll("[data-route-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      setActiveView(link.dataset.routeLink);
    });
  });

  document.querySelectorAll("[data-route-target]").forEach((button) => {
    button.addEventListener("click", () => {
      setActiveView(button.dataset.routeTarget);
    });
  });

  window.addEventListener("hashchange", () => {
    setActiveView(requestedView(), false);
  });
}

function bindEvents() {
  bindRoutes();
  byId("parseDump").addEventListener("click", () => parseBrainDump().catch(handleError));
  byId("generatePlan").addEventListener("click", () => generatePlan().catch(handleError));
  byId("generatePlanPrimary").addEventListener("click", () => generatePlan().catch(handleError));
  byId("addCommitment").addEventListener("click", () => addCommitment().catch(handleError));
  byId("connectGoogleCalendar").addEventListener("click", () => connectGoogleCalendar().catch(handleError));
  byId("refreshGoogleStatus").addEventListener("click", () => loadGoogleStatus().catch(handleError));
  byId("disconnectGoogleCalendar").addEventListener("click", () => disconnectGoogleCalendar().catch(handleError));
  byId("importGoogleCommitments").addEventListener("click", () => importGoogleCommitments().catch(handleError));
  byId("connectCanvas").addEventListener("click", () => connectCanvas().catch(handleError));
  byId("refreshCanvasStatus").addEventListener("click", () => loadCanvasStatus().catch(handleError));
  byId("disconnectCanvas").addEventListener("click", () => disconnectCanvas().catch(handleError));
  byId("importCanvasAssignments").addEventListener("click", () => importCanvasAssignments().catch(handleError));
  byId("submitCheckin").addEventListener("click", () => submitCheckin().catch(handleError));
  byId("loadSeed").addEventListener("click", () => loadSeedPlan().catch(handleError));
  byId("replanStrategy").addEventListener("click", () => replanWithStrategy().catch(handleError));
  byId("replanRL").addEventListener("click", () => replanWithRL().catch(handleError));
  byId("trainSelector").addEventListener("click", () => trainSelector().catch(handleError));
  byId("profileId").addEventListener("change", () => {
    renderGoogleImportSummary(null);
    renderCanvasImportSummary(null);
    loadProfileData().catch(handleError);
  });
  byId("profileId").addEventListener("blur", () => {
    renderGoogleImportSummary(null);
    renderCanvasImportSummary(null);
    loadProfileData().catch(handleError);
  });
  byId("commitmentList").addEventListener("click", (event) => {
    const button = event.target.closest("[data-delete-commitment]");
    if (!button) {
      return;
    }
    deleteCommitment(button.dataset.deleteCommitment).catch(handleError);
  });
}

function handleError(error) {
  console.error(error);
  alert(`UMass Study Partner error: ${error.message}`);
}

async function init() {
  setWeekStartDefault();
  bindEvents();
  setActiveView(requestedView(), false);
  renderScores();
  renderMetrics(null);
  renderParsedTasks([]);
  renderCommitments([]);
  renderCanvasCourses([]);
  renderCanvasImportSummary(null);
  renderGoogleCalendars([]);
  renderGoogleImportSummary(null);
  renderRepairSummary({}, "strategy");
  renderSelectorSummary({
    episodes: 0,
    unique_states: 0,
    average_reward: 0,
    final_epsilon: 0,
    action_counts: {},
  });
  await Promise.all([loadStrategies(), loadProfileData()]).catch(handleError);
}

init();
