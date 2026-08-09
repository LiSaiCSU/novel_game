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

const store = {
  sessionId: localStorage.getItem("sessionId") || null,
  worldId: localStorage.getItem("worldId") || null,
  playerId: localStorage.getItem("playerId") || null,
  debugMode: false,
  lastDebug: null,
  busy: false,
};

// ---------------------------------------------------------------- rendering
function paragraphs(text) {
  return (text || "")
    .split(/\n{2,}|\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function appendEntry({ said, prose, rejected, deltas }) {
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

  if (rejected) {
    const el = document.createElement("div");
    el.className = "rejected";
    el.textContent = `${rejected.reason_code}${rejected.reason ? " — " + rejected.reason : ""}`;
    entry.appendChild(el);
  }

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
  story.scrollTop = story.scrollHeight;
  return body;
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
    out.push({ dir: "up", text: `获得 ${item.item_key} ×${item.quantity}` });
  }
  for (const item of (sc.inventory || {}).removed || []) {
    out.push({ dir: "down", text: `失去 ${item.item_key} ×${item.quantity}` });
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
  $("sDanger").textContent = "★".repeat(Math.min(5, loc.danger_level || 0)) || "—";
  $("sDesc").textContent = loc.description || "";
  if (state.narrative_tension !== undefined) {
    $("sTension").textContent = state.narrative_tension;
  }

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
          <div class="meta">${escapeHtml(c.realm || "")}${c.faction ? " · " + escapeHtml(c.faction) : ""}</div>
        </div>`
      )
      .join("");
  }
}

function renderChoices(choices) {
  const box = $("choices");
  box.innerHTML = "";
  const templates = { TALK: (l) => `我找${l}说几句`, MOVE: (l) => `我去${l}`, CULTIVATE: () => "我打坐修炼一个时辰" };
  for (const c of choices || []) {
    const make = templates[c.action_type];
    if (!make) continue;
    const text = make(c.label);
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.textContent = text;
    chip.onclick = () => {
      $("playerInput").value = text;
      $("playerInput").focus();
    };
    box.appendChild(chip);
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
        const dims = Object.entries(r.dimensions)
          .filter(([, v]) => v)
          .map(([k, v]) => `<span class="tag">${k} ${v}</span>`)
          .join("");
        return `<div class="npc"><div class="name">${escapeHtml(r.with_name)}</div><div>${dims || '<span class="muted">初见</span>'}</div></div>`;
      })
      .join("");
  },
  quests: async () => {
    const rows = await api(`/game/${store.sessionId}/quests`);
    const open = rows.filter((r) => ["offered", "active"].includes(r.status));
    if (!open.length) return `<p class="muted">你眼下没有接下任何差事。</p>`;
    return open
      .map(
        (r) => `<div class="kv"><span>${escapeHtml(r.name)}</span><span class="tag">${r.status}</span></div>`
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

  try {
    const response = await fetch(`/api/game/${store.sessionId}/action/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, debug: true }),
    });
    if (!response.ok) throw new Error(await response.text());

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let prose = "";
    let payload = null;

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
        if (event === "state") {
          payload = data;
          // World state is committed before a single character of prose.
          renderState(data.visible_updates || {});
          renderChoices(data.choices);
          if (data.debug) renderDebug(data.debug);
        } else if (event === "narrative") {
          prose += data.delta;
          body.innerHTML = "";
          for (const p of paragraphs(prose)) {
            const node = document.createElement("p");
            node.textContent = p;
            body.appendChild(node);
          }
          $("story").scrollTop = $("story").scrollHeight;
        }
      }
    }

    body.classList.remove("cursor");
    if (payload) {
      const entry = body.parentElement;
      if (payload.rejected) {
        const el = document.createElement("div");
        el.className = "rejected";
        el.textContent = `${payload.rejected.reason_code}${payload.rejected.reason ? " — " + payload.rejected.reason : ""}`;
        entry.appendChild(el);
      }
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
    const el = document.createElement("div");
    el.className = "rejected";
    el.textContent = `请求失败：${e.message}`;
    body.parentElement.appendChild(el);
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
      }),
    });
    store.sessionId = data.session_id;
    store.worldId = data.world_id;
    store.playerId = data.player_character_id;
    localStorage.setItem("sessionId", data.session_id);
    localStorage.setItem("worldId", data.world_id);
    localStorage.setItem("playerId", data.player_character_id);
    await enterGame(data.opening, data.state);
  } catch (e) {
    $("setupErr").textContent = e.message;
  } finally {
    $("startBtn").disabled = false;
  }
};

async function enterGame(opening, state) {
  $("setup").style.display = "none";
  $("app").style.display = "grid";
  if (opening) appendEntry({ prose: opening });
  if (state) renderState(state);
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
    localStorage.clear();
    store.sessionId = null;
  }
})();
