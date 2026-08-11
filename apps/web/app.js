// AI Narrative World Engine - browser client.
// Zero build step by design (DECISIONS D-002): the REST/SSE contract is the
// only coupling, so a Next.js port later needs no backend change.

const $ = (id) => document.getElementById(id);
const api = (path, options) =>
  fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  }).then(async (r) => {
    if (!r.ok) throw new Error((await r.text()) || r.statusText);
    return r.json();
  });

const MIN_NARRATIVE_CHARS = 400;
const MAX_NARRATIVE_CHARS = 4000;
const DEFAULT_NARRATIVE_CHARS = 1800;

function clampNarrativeLength(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return DEFAULT_NARRATIVE_CHARS;
  return Math.round(
    Math.max(MIN_NARRATIVE_CHARS, Math.min(MAX_NARRATIVE_CHARS, parsed)) / 100
  ) * 100;
}

const store = {
  sessionId: localStorage.getItem("sessionId") || null,
  worldId: localStorage.getItem("worldId") || null,
  playerId: localStorage.getItem("playerId") || null,
  narrativeMaxChars: clampNarrativeLength(
    localStorage.getItem("narrativeMaxChars") || DEFAULT_NARRATIVE_CHARS
  ),
  debugMode: false,
  lastDebug: null,
  busy: false,
  //: Whether the story pane should keep following new text.
  follow: true,
};

function syncNarrativeLength(value) {
  store.narrativeMaxChars = clampNarrativeLength(value);
  localStorage.setItem("narrativeMaxChars", String(store.narrativeMaxChars));
  for (const id of [
    "setupLengthRange",
    "setupLengthMax",
    "turnLengthRange",
    "turnLengthMax",
  ]) {
    if ($(id)) $(id).value = String(store.narrativeMaxChars);
  }
}

for (const id of ["setupLengthRange", "turnLengthRange"]) {
  $(id).addEventListener("input", (event) => syncNarrativeLength(event.target.value));
}
for (const id of ["setupLengthMax", "turnLengthMax"]) {
  $(id).addEventListener("change", (event) => syncNarrativeLength(event.target.value));
}
syncNarrativeLength(store.narrativeMaxChars);

function newIdempotencyKey() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// ---------------------------------------------------------------- rendering
function paragraphs(text) {
  return (text || "")
    .split(/\n{2,}|\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function appendEntry({ said, prose, deltas }) {
  const story = $("story");
  const entry = document.createElement("div");
  entry.className = "entry";

  if (said) {
    const el = document.createElement("div");
    el.className = "said";
    el.textContent = said;
    entry.appendChild(el);
  }

  const body = document.createElement("div");
  body.className = "prose";
  for (const p of paragraphs(prose)) {
    const node = document.createElement("p");
    node.textContent = p;
    body.appendChild(node);
  }
  entry.appendChild(body);

  if (deltas && deltas.length) {
    const row = document.createElement("div");
    row.className = "deltas";
    for (const d of deltas) {
      const chip = document.createElement("span");
      chip.className = d.dir;
      chip.textContent = d.text;
      row.appendChild(chip);
    }
    entry.appendChild(row);
  }

  story.appendChild(entry);
  followIfAtBottom(story);
  return body;
}

// Auto-scroll is a courtesy, not a right. A chapter streams for a minute; if
// the reader has scrolled up to re-read something, yanking them back to the
// bottom on every chunk makes the text unreadable. So: follow only while they
// are already at the bottom, and stop the moment they scroll away.
const NEAR_BOTTOM_PX = 80;

function isNearBottom(el) {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
}

function followIfAtBottom(el) {
  if (store.follow) el.scrollTop = el.scrollHeight;
}

function describeDeltas(sc) {
  const out = [];
  const names = {
    health: "气血",
    spiritual_power: "灵力",
    cultivation_progress: "修为",
    injuries: "伤势",
    mental_state: "心境",
    realm: "境界",
    location: "位置",
  };
  for (const [key, pair] of Object.entries(sc.character || {})) {
    if (!Array.isArray(pair)) continue;
    const [a, b] = pair;
    const label = names[key] || key;
    if (typeof a === "number" && typeof b === "number") {
      const diff = b - a;
      if (Math.abs(diff) < 1e-6) continue;
      const shown = key === "cultivation_progress" || key === "injuries" || key === "mental_state"
        ? (diff * 100).toFixed(1) + "%"
        : diff.toFixed(0);
      out.push({ dir: diff > 0 ? "up" : "down", text: `${label} ${diff > 0 ? "+" : ""}${shown}` });
    } else {
      out.push({ dir: "up", text: `${label} ${a} → ${b}` });
    }
  }
  for (const item of (sc.inventory || {}).added || []) {
    out.push({ dir: "up", text: `获得 ${item.name || item.item_key} ×${item.quantity}` });
  }
  for (const item of (sc.inventory || {}).removed || []) {
    out.push({ dir: "down", text: `失去 ${item.name || item.item_key} ×${item.quantity}` });
  }
  const minutes = sc.world_minute;
  if (Array.isArray(minutes) && minutes[1] > minutes[0]) {
    out.push({ dir: "up", text: `时间 +${minutes[1] - minutes[0]} 分` });
  }
  return out;
}

// ---------------------------------------------------------------- state view
function renderState(state) {
  const p = state.player || {};
  $("cName").textContent = p.name || "—";
  $("cRealm").textContent = p.realm || "—";

  const [hp, hpMax] = p.health || [0, 1];
  const [mp, mpMax] = p.spiritual_power || [0, 1];
  $("hpText").textContent = `${hp} / ${hpMax}`;
  $("mpText").textContent = `${mp} / ${mpMax}`;
  $("hpBar").style.width = `${Math.max(0, (hp / Math.max(1, hpMax)) * 100)}%`;
  $("mpBar").style.width = `${Math.max(0, (mp / Math.max(1, mpMax)) * 100)}%`;

  const xp = p.cultivation_progress || 0;
  $("xpText").textContent = `${(xp * 100).toFixed(1)}%`;
  $("xpBar").style.width = `${xp * 100}%`;

  $("cInjury").textContent = ((p.injuries || 0) * 100).toFixed(0) + "%";
  $("cMental").textContent = ((p.mental_state || 0) * 100).toFixed(0) + "%";

  const loc = state.location || {};
  const time = state.time || {};
  $("sTime").textContent = time.label || "—";
  $("sPlace").textContent = loc.name || "—";

  // Always-visible clock: which part of the day it is, and what o'clock.
  if (time.phase_name || time.hour !== undefined) {
    $("nowPhase").textContent = time.phase_name || "";
    const hh = String(time.hour ?? 0).padStart(2, "0");
    const mm = String(time.minute ?? 0).padStart(2, "0");
    $("nowClock").textContent = `${hh}:${mm}`;
    const stamp = [time.year && `${time.year}年`, time.month && `${time.month}月`, time.day && `${time.day}日`]
      .filter(Boolean)
      .join("");
    $("nowDate").textContent = time.hour_label ? `${stamp} ${time.hour_label}` : stamp;
    $("nowPlace").textContent = loc.name || "";
  }
  $("sDanger").textContent = "★".repeat(Math.min(5, loc.danger_level || 0)) || "—";
  $("sDesc").textContent = loc.description || "";
  // narrative_tension is a director dial, not something a reader should see.

  const npcs = state.present_characters || [];
  const box = $("sNpcs");
  if (!npcs.length) {
    box.className = "muted";
    box.textContent = "此处只有你一人。";
  } else {
    box.className = "";
    box.innerHTML = npcs
      .map(
        (c) => `<div class="npc">
          <div class="name">${escapeHtml(c.name)}</div>
          <div class="meta">${escapeHtml(c.realm || "")}${c.title ? " · " + escapeHtml(c.title) : ""}${c.faction ? " · " + escapeHtml(c.faction) : ""}</div>
        </div>`
      )
      .join("");
  }
}

function chip(text, { primary = false, send = false } = {}) {
  const el = document.createElement("button");
  el.className = primary ? "chip primary" : "chip";
  el.textContent = text;
  el.onclick = () => {
    $("playerInput").value = text;
    if (send) submit();
    else $("playerInput").focus();
  };
  return el;
}

// The beat is what the scene is waiting on. When it is not waiting on
// anything, the only thing worth offering is "keep going".
function renderChoices(choices, beat) {
  const box = $("choices");
  box.innerHTML = "";

  if (beat && beat.question) {
    const q = document.createElement("div");
    q.className = "beatQuestion";
    q.textContent = beat.question;
    box.appendChild(q);
  }

  const options = (beat && beat.options) || [];
  for (const o of options) box.appendChild(chip(o.label, { send: true }));

  if (!beat || beat.needs_player === false) {
    box.appendChild(chip("继续", { primary: true, send: true }));
  }

  if (!options.length) {
    const templates = {
      TALK: (l) => `我找${l}说几句`,
      MOVE: (l) => `我去${l}`,
      CULTIVATE: () => "我打坐修炼一个时辰",
    };
    for (const c of choices || []) {
      const make = templates[c.action_type];
      if (!make) continue;
      box.appendChild(chip(make(c.label)));
    }
  }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// ---------------------------------------------------------------- side tabs
const tabRenderers = {
  inventory: async () => {
    const rows = await api(`/game/${store.sessionId}/inventory`);
    if (!rows.length) return `<p class="muted">你身无长物。</p>`;
    return rows
      .map(
        (r) => `<div class="kv"><span>${escapeHtml(r.name)}</span><span>×${r.quantity}</span></div>`
      )
      .join("");
  },
  relationships: async () => {
    const rows = await api(`/game/${store.sessionId}/relationships`);
    if (!rows.length) return `<p class="muted">你还没有真正认识什么人。</p>`;
    return rows
      .map((r) => {
        const role = (r.tags || []).includes("co_protagonist")
          ? '<span class="tag leadTag">共同主角</span>'
          : "";
        const dims = Object.entries(r.dimensions)
          .filter(([, v]) => v)
          .map(([k, v]) => `<span class="tag">${k} ${v}</span>`)
          .join("");
        return `<div class="npc"><div class="name">${escapeHtml(r.with_name)} ${role}</div><div>${dims || '<span class="muted">初见</span>'}</div></div>`;
      })
      .join("");
  },
  quests: async () => {
    const rows = await api(`/game/${store.sessionId}/quests`);
    const open = rows.filter((r) => ["offered", "active"].includes(r.status));
    if (!open.length) return `<p class="muted">你眼下没有接下任何差事。</p>`;
    return open
      .map(
        (r) => `<div class="kv"><span>${escapeHtml(r.name)}</span><span class="tag">${escapeHtml(r.status_label || r.status)}</span></div>`
      )
      .join("");
  },
  history: async () => {
    const rows = await api(`/game/${store.sessionId}/history?limit=20`);
    if (!rows.length) return `<p class="muted">尚无记录。</p>`;
    return rows
      .slice()
      .reverse()
      .map(
        (r) => `<div class="npc"><div class="name">#${r.turn_number} ${escapeHtml(r.player_input)}</div>
                 <div class="meta">${escapeHtml((r.narrative || "").slice(0, 48))}…</div></div>`
      )
      .join("");
  },
};

let activeTab = "inventory";
async function refreshTab() {
  const body = $("tabBody");
  try {
    body.innerHTML = await tabRenderers[activeTab]();
  } catch (e) {
    body.innerHTML = `<p class="muted">读取失败：${escapeHtml(e.message)}</p>`;
  }
}

$("leftTabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  activeTab = btn.dataset.tab;
  [...$("leftTabs").children].forEach((b) => b.classList.toggle("active", b === btn));
  refreshTab();
});

// ---------------------------------------------------------------- debug
function renderDebug(debug) {
  store.lastDebug = debug;
  if (!debug) return;
  $("dbgTurn").textContent = `turn ${debug.turn_id?.slice(0, 8) ?? ""}`;
  const usage = debug.token_usage || {};
  $("dbgTokens").textContent = `tokens ${usage.prompt || 0}/${usage.completion || 0}`;

  const sections = [
    ["Intent 解析", debug.intent],
    ["Rule 结果", debug.rule_result],
    ["Action 结果", debug.outcome],
    ["NPC Decisions", debug.npc_decisions],
    ["Director", debug.director],
    ["World Simulation", debug.simulation],
    ["Proposals（校验/钳制）", debug.proposals],
    ["Consistency", debug.consistency],
    ["State Changes", debug.state_changes],
    ["Memory", debug.memory],
    ["Context 快照", debug.context_snapshots],
    ["LLM Calls", debug.llm_calls],
    ["RNG", debug.rng_traces],
    ["Stage Timings (ms)", debug.stage_timings],
    ["Narrative 风格检查", debug.narrative_style],
    ["Errors", debug.errors],
  ];

  $("debugBody").innerHTML = sections
    .map(([title, data]) => {
      const empty = data == null || (Array.isArray(data) && !data.length) ||
        (typeof data === "object" && !Array.isArray(data) && !Object.keys(data).length);
      const count = Array.isArray(data) ? ` (${data.length})` : "";
      return `<details class="dbg"${empty ? "" : ""}>
        <summary>${title}${count}${empty ? " — 空" : ""}</summary>
        <div><pre class="json">${escapeHtml(JSON.stringify(data, null, 2))}</pre></div>
      </details>`;
    })
    .join("");
}

$("toggleDebug").onclick = () => $("debugPanel").classList.toggle("open");
$("closeDebug").onclick = () => $("debugPanel").classList.remove("open");

// ---------------------------------------------------------------- turn loop
async function submit() {
  const input = $("playerInput");
  const text = input.value.trim();
  if (!text || store.busy) return;

  store.busy = true;
  $("sendBtn").disabled = true;
  input.value = "";

  const body = appendEntry({ said: text, prose: "" });
  body.classList.add("cursor");
  const idempotencyKey = newIdempotencyKey();

  try {
    const response = await fetch(`/api/game/${store.sessionId}/action/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        debug: true,
        idempotency_key: idempotencyKey,
        narrative_max_chars: store.narrativeMaxChars,
      }),
    });
    if (!response.ok) throw new Error(await response.text());

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let prose = "";
    let payload = null;
    const progress = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";
      for (const frame of frames) {
        const evLine = frame.split("\n").find((l) => l.startsWith("event:"));
        const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!evLine || !dataLine) continue;
        const event = evLine.slice(6).trim();
        const data = JSON.parse(dataLine.slice(5));
        if (event === "progress") {
          // The chapter is still being played out; show it moving.
          progress.push(data);
          body.innerHTML = "";
          const node = document.createElement("p");
          node.className = "progress";
          node.textContent = `故事正在推进…（第 ${data.step} 回合）`;
          body.appendChild(node);
        } else if (event === "error") {
          throw new Error(data.message || "回合失败");
        } else if (event === "state") {
          payload = data;
          // World state is committed before a single character of prose.
          renderState(data.visible_updates || {});
          renderChoices(data.choices, data.beat);
          if (data.debug) renderDebug(data.debug);
        } else if (event === "narrative") {
          // First prose chunk replaces the progress placeholder.
          prose += data.delta;
          body.innerHTML = "";
          for (const p of paragraphs(prose)) {
            const node = document.createElement("p");
            node.textContent = p;
            body.appendChild(node);
          }
          followIfAtBottom($("story"));
        }
      }
    }

    body.classList.remove("cursor");
    if (payload) {
      const entry = body.parentElement;
      // How many turns a chapter covers is bookkeeping, not story. It belongs
      // in the debug panel, not under the prose.
      // A refusal is already written into the prose. Reason codes are for the
      // debug panel, not for the reader.
      const deltas = describeDeltas(payload.state_changes || {});
      if (deltas.length) {
        const row = document.createElement("div");
        row.className = "deltas";
        for (const d of deltas) {
          const chip = document.createElement("span");
          chip.className = d.dir;
          chip.textContent = d.text;
          row.appendChild(chip);
        }
        entry.appendChild(row);
      }
    }
    await refreshTab();
    await refreshState();
  } catch (e) {
    body.classList.remove("cursor");
    // The world is committed before any prose is streamed, so a dropped
    // connection loses the telling, never the turn. Recover the chapter from
    // the server instead of leaving the player staring at an error.
    const recovered = await recoverAfterDroppedStream();
    if (!recovered) {
      const el = document.createElement("div");
      el.className = "rejected";
      el.textContent = `连接中断：${e.message}。你的进度已保存，可以直接继续。`;
      body.parentElement.appendChild(el);
    }
  } finally {
    store.busy = false;
    $("sendBtn").disabled = false;
    input.focus();
  }
}

async function refreshState() {
  try {
    const state = await api(`/game/${store.sessionId}/state`);
    renderState(state);
  } catch {
    /* the scene panel is best-effort */
  }
}

$("sendBtn").onclick = submit;
$("playerInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    submit();
  }
});
$("playerInput").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(130, e.target.scrollHeight) + "px";
});

// ---------------------------------------------------------------- boot
$("startBtn").onclick = async () => {
  const name = $("pName").value.trim();
  if (!name) {
    $("setupErr").textContent = "请先取个名字。";
    return;
  }
  $("startBtn").disabled = true;
  $("setupErr").textContent = "";
  try {
    const data = await api("/game/start", {
      method: "POST",
      body: JSON.stringify({
        player_name: name,
        gender: $("pGender").value,
        age: Number($("pAge").value) || 18,
        background: $("pBackground").value.trim(),
        world_seed: `web-${Date.now()}`,
        narrative_max_chars: store.narrativeMaxChars,
      }),
    });
    store.sessionId = data.session_id;
    store.worldId = data.world_id;
    store.playerId = data.player_character_id;
    localStorage.setItem("sessionId", data.session_id);
    localStorage.setItem("worldId", data.world_id);
    localStorage.setItem("playerId", data.player_character_id);
    await enterGame(data.opening, data.state, data.beat);
  } catch (e) {
    $("setupErr").textContent = e.message;
  } finally {
    $("startBtn").disabled = false;
  }
};

async function enterGame(opening, state, beat) {
  $("setup").style.display = "none";
  $("app").style.display = "grid";
  if (opening) appendEntry({ prose: opening });
  if (state) renderState(state);
  renderChoices([], beat);
  await refreshState();
  await refreshTab();
  $("playerInput").focus();
}

(async function boot() {
  try {
    const health = await api("/health");
    store.debugMode = !!health.debug_mode;
    $("toggleDebug").style.display = store.debugMode ? "block" : "none";
  } catch {
    /* the API may still be starting */
  }

  if (!store.sessionId) return;
  try {
    const state = await api(`/game/${store.sessionId}/state`);
    const history = await api(`/game/${store.sessionId}/history?limit=12`);
    await enterGame(null, state);
    for (const turn of history) {
      appendEntry({ said: turn.player_input, prose: turn.narrative });
    }
  } catch {
    // stale session: fall back to the setup screen
    localStorage.removeItem("sessionId");
    localStorage.removeItem("worldId");
    localStorage.removeItem("playerId");
    store.sessionId = null;
  }
})();

// ---------------------------------------------------------------- save / load
async function refreshSaveList() {
  const box = $("saveList");
  try {
    const saves = await api(`/game/${store.sessionId}/saves`);
    if (!saves.length) {
      box.className = "muted";
      box.textContent = "还没有存档。先点「存档」把当前进度存下来。";
      return;
    }
    box.className = "";
    box.innerHTML = "";
    for (const s of saves) {
      const row = document.createElement("div");
      row.className = "saveRow";
      const when = s.created_at ? new Date(s.created_at).toLocaleString() : "";
      row.innerHTML = `
        <div class="saveMain">
          <div class="saveName">${escapeHtml(s.name || "未命名存档")}</div>
          <div class="saveMeta">${escapeHtml(s.time_label || "")}${
            s.location_name ? " · " + escapeHtml(s.location_name) : ""
          } · 第 ${s.turn_number} 回合</div>
          <div class="saveExcerpt">${escapeHtml(s.excerpt || "")}</div>
          <div class="saveMeta">${escapeHtml(when)}</div>
        </div>`;
      const actions = document.createElement("div");
      actions.className = "saveActions";
      const load = document.createElement("button");
      load.className = "chip primary";
      load.textContent = "读取";
      load.onclick = () => loadSave(s.id);
      const del = document.createElement("button");
      del.className = "chip";
      del.textContent = "删除";
      del.onclick = async () => {
        if (!confirm(`删除存档「${s.name || "未命名存档"}」？`)) return;
        await api(`/game/saves/${s.id}`, { method: "DELETE" });
        await refreshSaveList();
      };
      actions.append(load, del);
      row.appendChild(actions);
      box.appendChild(row);
    }
  } catch (e) {
    box.className = "err";
    box.textContent = `读取存档失败：${e.message}`;
  }
}

async function loadSave(saveId) {
  // Loading throws away everything after the save, so it is worth a question.
  if (!confirm("读取存档会丢弃此后发生的一切，确定吗？")) return;
  try {
    await api(`/game/saves/${saveId}/load`, { method: "POST" });
    $("saveModal").style.display = "none";
    const opening = await api(`/game/${store.sessionId}/opening`);
    $("story").innerHTML = "";
    for (const chapter of opening.chapters) appendEntry({ prose: chapter });
    renderState(opening.state || {});
    renderChoices([], opening.beat);
    await refreshState();
    await refreshTab();
  } catch (e) {
    alert(`读档失败：${e.message}`);
  }
}

$("saveBtn").onclick = async () => {
  const suggested = $("nowPhase").textContent + " " + $("nowPlace").textContent;
  const name = prompt("给这个存档起个名字：", suggested.trim());
  if (name === null) return;
  try {
    await api(`/game/${store.sessionId}/saves`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    $("saveBtn").textContent = "已存档";
    setTimeout(() => ($("saveBtn").textContent = "存档"), 1600);
  } catch (e) {
    alert(`存档失败：${e.message}`);
  }
};

$("loadBtn").onclick = async () => {
  $("saveModal").style.display = "flex";
  await refreshSaveList();
};
$("closeSaves").onclick = () => ($("saveModal").style.display = "none");

$("restartBtn").onclick = () => {
  if (!confirm("重新开始会开一局全新的游戏。当前进度仍可通过存档找回，确定吗？")) return;
  localStorage.removeItem("sessionId");
  localStorage.removeItem("worldId");
  localStorage.removeItem("playerId");
  store.sessionId = null;
  $("story").innerHTML = "";
  $("choices").innerHTML = "";
  $("app").style.display = "none";
  $("setup").style.display = "flex";
};

// ---------------------------------------------------------------- scrolling
// The reader decides whether the view follows the text.
(function wireScrollFollow() {
  const story = $("story");
  const jump = $("jumpLatest");

  story.addEventListener("scroll", () => {
    store.follow = isNearBottom(story);
    jump.style.display = store.follow ? "none" : "block";
  });

  jump.onclick = () => {
    store.follow = true;
    jump.style.display = "none";
    story.scrollTop = story.scrollHeight;
  };
})();

// A dropped stream costs the prose, not the progress: the run is committed
// before a single character is sent. Pull the finished chapter back down.
async function recoverAfterDroppedStream() {
  for (const waitMs of [1500, 4000, 8000]) {
    await new Promise((r) => setTimeout(r, waitMs));
    try {
      const opening = await api(`/game/${store.sessionId}/opening`);
      if (!opening.chapters || !opening.chapters.length) continue;
      $("story").innerHTML = "";
      for (const chapter of opening.chapters) appendEntry({ prose: chapter });
      renderState(opening.state || {});
      renderChoices([], opening.beat);
      await refreshState();
      await refreshTab();
      return true;
    } catch {
      /* the run may still be finishing; try again */
    }
  }
  return false;
}
