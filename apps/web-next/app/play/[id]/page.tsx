"use client";

import {FormEvent, KeyboardEvent, useEffect, useRef, useState} from "react";
import {useParams} from "next/navigation";
import {api, streamApi} from "@/lib/api";

type Character = {name: string; title?: string; faction?: string};
type Scene = {
  time?: {label?: string};
  location?: {name?: string; description?: string};
  player?: {name?: string; health?: number[]; realm?: string};
  present_characters?: Character[];
  playthrough?: {status: string; ending_key?: string | null; ending_title?: string | null};
};
type Choice = {label: string; hint?: string; action_type?: string};
type History = {chapters: Array<{input: string; text: string}>; choices: Choice[]};
type Save = {id: string; name: string; turn_number: number; time_label: string; location_name: string; excerpt: string};
type Relationship = {key: string; name: string; dimensions: Record<string, number>; tags: string[]};
type Dashboard = {
  player: {attributes: Record<string, unknown>; resources: Record<string, unknown>; progressions: Record<string, unknown>; properties: Record<string, unknown>};
  inventory: Array<{key: string; name: string; quantity: number}>;
  abilities: Array<{key: string; name: string; mastery: number}>;
  relationships: Relationship[];
  quests: Array<{key: string; name: string; status: string}>;
  threads: Array<{key: string; name: string; status: string; stage: number; next_beat_hint: string}>;
  labels: {relationships: Record<string, string>; statuses: Record<string, string>; attributes: Record<string, string>; resources: Record<string, string>; progressions: Record<string, string>};
};
type Ending = {key: string; title: string; type: string; lead?: string; available: boolean; epilogue: string};
type EndingStatus = {
  status: string;
  selected?: {key: string; title: string} | null;
  endings: Ending[];
  hidden_count: number;
  consent: Record<string, string>;
  leads: Record<string, string>;
};
type Recap = {
  title: string;
  turn_number: number;
  updated_at: string;
  scene: {time: string; location: string};
  last_action: string;
  recent: Array<{text: string; world_minute: number}>;
  objectives: Array<{type: string; key: string; name: string; hint: string}>;
  suggestions: Choice[];
};

const initialChoices: Choice[] = [
  {label: "环顾四周", hint: "了解当前场景与可互动线索"},
  {label: "梳理当前目标", hint: "回顾眼下最重要的事情"},
  {label: "和在场的人交谈", hint: "主动开启一段对话"},
];

function metric(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value !== "object") return String(value);
  const data = value as Record<string, unknown>;
  const maximum = data.max ?? data.maximum;
  if (data.current !== undefined && maximum !== undefined) return `${String(data.current)} / ${String(maximum)}`;
  if (data.value !== undefined) return String(data.value);
  return Object.entries(data).map(([key, item]) => `${key}: ${String(item)}`).join(" · ");
}

export default function Game() {
  const {id} = useParams<{id: string}>();
  const [state, setState] = useState<Scene>();
  const [chapters, setChapters] = useState<string[]>([]);
  const [current, setCurrent] = useState<{input: string; narrative: string}>();
  const [choices, setChoices] = useState<Choice[]>(initialChoices);
  const [beat, setBeat] = useState("");
  const [draft, setDraft] = useState("");
  const [saves, setSaves] = useState<Save[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard>();
  const [endingStatus, setEndingStatus] = useState<EndingStatus>();
  const [recap, setRecap] = useState<Recap>();
  const [showRecap, setShowRecap] = useState(true);
  const [railTab, setRailTab] = useState("人物");
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const form = useRef<HTMLFormElement>(null);

  async function refresh() {
    const [nextState, history, saved, nextDashboard, endings] = await Promise.all([
      api<Scene>(`/playthroughs/${id}/state`),
      api<History>(`/playthroughs/${id}/history`),
      api<Save[]>(`/playthroughs/${id}/saves`),
      api<Dashboard>(`/playthroughs/${id}/dashboard`),
      api<EndingStatus>(`/playthroughs/${id}/endings`),
    ]);
    setState(nextState);
    setChapters(history.chapters.map(item => item.input ? `你：${item.input}\n\n${item.text}` : item.text));
    if (history.choices.length) setChoices(history.choices);
    setSaves(saved);
    setDashboard(nextDashboard);
    setEndingStatus(endings);
  }

  useEffect(() => {
    Promise.all([
      api<Scene>(`/playthroughs/${id}/state`),
      api<History>(`/playthroughs/${id}/history`),
      api<Save[]>(`/playthroughs/${id}/saves`),
      api<Dashboard>(`/playthroughs/${id}/dashboard`),
      api<EndingStatus>(`/playthroughs/${id}/endings`),
      api<Recap>(`/playthroughs/${id}/recap`),
    ]).then(([nextState, history, saved, nextDashboard, endings, returnRecap]) => {
      setState(nextState);
      setChapters(history.chapters.map(item => item.input ? `你：${item.input}\n\n${item.text}` : item.text));
      if (history.choices.length) setChoices(history.choices);
      setSaves(saved);
      setDashboard(nextDashboard);
      setEndingStatus(endings);
      setRecap(returnRecap);
      if (returnRecap.suggestions.length) setChoices(returnRecap.suggestions);
    }).catch(exception => setError(exception.message));
  }, [id]);
  useEffect(() => end.current?.scrollIntoView({behavior: "smooth"}), [chapters, current]);

  async function act(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setBusy(true);
    setError("");
    setBeat("");
    setCurrent({input: text, narrative: ""});
    setProgress("正在理解你的意图");
    setDraft("");
    let narrative = "";
    let nextState: Scene | undefined;
    try {
      await streamApi(
        `/playthroughs/${id}/actions/stream`,
        {text, idempotency_key: crypto.randomUUID()},
        (streamEvent, payload) => {
          if (streamEvent === "narrative") {
            narrative += String(payload.delta ?? "");
            setCurrent({input: text, narrative});
          } else if (streamEvent === "progress") {
            const summary = String(payload.summary ?? "");
            setProgress(summary ? `世界变化：${summary}` : `世界已推进 ${String(payload.minutes ?? 0)} 分钟`);
          } else if (streamEvent === "state") {
            nextState = payload.visible_updates as Scene;
            setState(nextState);
            const nextChoices = (payload.choices as Choice[] | undefined) ?? [];
            if (nextChoices.length) setChoices(nextChoices);
            const nextBeat = payload.beat as {question?: string; options?: Choice[]} | null;
            setBeat(nextBeat?.question ?? "");
            if (nextBeat?.options?.length) setChoices(nextBeat.options);
          } else if (streamEvent === "error") {
            throw new Error(String(payload.message ?? "行动失败"));
          }
        },
      );
      setCurrent(undefined);
      await refresh();
    } catch (exception) {
      setError((exception as Error).message);
      setDraft(text);
    } finally {
      setProgress("");
      setBusy(false);
    }
  }

  function choose(label: string) {
    setDraft(label);
    requestAnimationFrame(() => form.current?.querySelector("textarea")?.focus());
  }

  function keyboardSubmit(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) form.current?.requestSubmit();
  }

  async function createSave() {
    const name = `第 ${chapters.length} 章 · ${state?.time?.label ?? "当前进度"}`;
    await api(`/playthroughs/${id}/saves`, {method: "POST", body: JSON.stringify({name})});
    setSaves(await api<Save[]>(`/playthroughs/${id}/saves`));
  }

  async function loadSave(save: Save) {
    if (!window.confirm(`回到“${save.name}”？该存档之后的进度会被覆盖。`)) return;
    await api(`/playthroughs/${id}/saves/${save.id}/load`, {method: "POST"});
    await refresh();
  }

  async function deleteSave(save: Save) {
    if (!window.confirm(`删除存档“${save.name}”？`)) return;
    await api(`/playthroughs/${id}/saves/${save.id}`, {method: "DELETE"});
    setSaves(items => items.filter(item => item.id !== save.id));
  }

  async function setConsent(lead: string, decision: string) {
    await api(`/playthroughs/${id}/relationships/${lead}/consent`, {
      method: "PUT",
      body: JSON.stringify({decision}),
    });
    setEndingStatus(await api<EndingStatus>(`/playthroughs/${id}/endings`));
    setDashboard(await api<Dashboard>(`/playthroughs/${id}/dashboard`));
  }

  async function chooseEnding(ending: Ending) {
    if (!window.confirm(`以“${ending.title}”结束这一局？之后仍可读取较早的手动存档。`)) return;
    await api(`/playthroughs/${id}/ending`, {
      method: "POST",
      body: JSON.stringify({ending_key: ending.key}),
    });
    await refresh();
  }

  const completed = state?.playthrough?.status === "completed";

  return <div className="gameShell">
    <aside className="gameRail">
      <p className="eyebrow">当前场景</p><h2>{state?.location?.name ?? "正在抵达…"}</h2>
      <p className="railCopy">{state?.location?.description}</p>
      <div className="statRow"><span>时间</span><b>{state?.time?.label ?? "—"}</b></div>
      <button className="button saveButton" disabled={completed} onClick={() => createSave().catch(exception => setError(exception.message))}>保存当前进度</button>
      <h2 className="railSection">存档</h2>
      {saves.length === 0 && <p className="studioHint">还没有手动存档。每次行动本身也会写入历史。</p>}
      {saves.map(save => <article className="saveItem" key={save.id}><button onClick={() => loadSave(save).catch(exception => setError(exception.message))}><b>{save.name}</b><small>{save.location_name} · 回合 {save.turn_number}</small></button><button className="dangerLink" aria-label={`删除${save.name}`} onClick={() => deleteSave(save).catch(exception => setError(exception.message))}>删除</button></article>)}
    </aside>
    <section className="gameCenter">
      <div className="story" aria-live="polite">
        {showRecap && recap && recap.turn_number > 0 && <section className="returnRecap" aria-label="上次游戏回顾">
          <header><div><p className="eyebrow">WELCOME BACK</p><h2>回到 {recap.scene.location}</h2><small>{recap.scene.time} · 已进行 {recap.turn_number} 回合</small></div><button className="dangerLink" onClick={() => setShowRecap(false)}>收起</button></header>
          {recap.last_action && <p><b>你上次：</b>{recap.last_action}</p>}
          {recap.recent.length > 0 && <blockquote>{recap.recent.at(-1)?.text}</blockquote>}
          {recap.objectives.length > 0 && <div className="recapObjectives"><b>接下来可以关注</b>{recap.objectives.slice(0, 4).map(objective => <button key={`${objective.type}-${objective.key}`} title={objective.hint} onClick={() => choose(objective.hint || `继续推进${objective.name}`)}><span>{objective.name}</span>{objective.hint && <small>{objective.hint}</small>}</button>)}</div>}
        </section>}
        {chapters.length === 0 && <p>{state?.location?.description}</p>}
        {chapters.map((chapter, index) => <article key={index} className="chapter">{chapter}</article>)}
        {current && <article className="chapter">{`你：${current.input}\n\n${current.narrative}`}{busy && <span className="streamCursor" aria-hidden="true"/>}</article>}
        {busy && <p className="progressLine">{progress || "世界正在回应你的行动"}</p>}
        {error && <p className="error">{error}</p>}<div ref={end}/>
      </div>
      {completed && <div className="endingBanner"><span>本局已完成</span><b>{state?.playthrough?.ending_title}</b><small>你仍可以读取左侧较早的手动存档，继续探索另一种可能。</small></div>}
      <div className="decisionArea" aria-hidden={completed}>
        {beat && <p className="beatQuestion">{beat}</p>}
        {!completed && <div className="choiceRow">{choices.slice(0, 4).map(choice => <button type="button" key={choice.label} title={choice.hint} onClick={() => choose(choice.label)} disabled={busy}>{choice.label}</button>)}</div>}
      </div>
      <form className="composer" ref={form} onSubmit={act}>
        <textarea className="textarea" value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={keyboardSubmit} aria-label="描述你想做的事" placeholder={completed ? "本局已经抵达结局；读取较早存档可继续行动。" : "选择建议，或用自己的话行动。Ctrl / ⌘ + Enter 发送。"} disabled={completed}/>
        <button className="button primary" disabled={completed || busy || !draft.trim()}>行动</button>
      </form>
    </section>
    <aside className="gameRail gameDashboard">
      <div className="railTabs" role="tablist" aria-label="游戏状态">
        {["人物", "关系", "任务", "背包", "结局"].map(tab => <button key={tab} role="tab" aria-selected={railTab === tab} className={railTab === tab ? "active" : ""} onClick={() => setRailTab(tab)}>{tab}</button>)}
      </div>

      {railTab === "人物" && <section className="railPanel">
        <p className="eyebrow">主角</p><h2>{state?.player?.name}</h2>
        {Object.entries(dashboard?.player.resources ?? {}).map(([key, value]) => <div className="statRow" key={key}><span>{dashboard?.labels.resources[key] ?? key}</span><b>{metric(value)}</b></div>)}
        {Object.entries(dashboard?.player.progressions ?? {}).map(([key, value]) => <div className="statRow" key={key}><span>{dashboard?.labels.progressions[key] ?? key}</span><b>{metric(value)}</b></div>)}
        <h2 className="railSection">在场人物</h2>
        {state?.present_characters?.length ? state.present_characters.map(character => <div className="statRow" key={character.name}><span>{character.name}</span><b>{character.title || character.faction || ""}</b></div>) : <p className="studioHint">此刻没有其他人在场。</p>}
      </section>}

      {railTab === "关系" && <section className="railPanel">
        <p className="eyebrow">已建立的关系</p>
        {dashboard?.relationships.length ? dashboard.relationships.map(relationship => <article className="relationCard" key={relationship.key}>
          <h2>{relationship.name}</h2>
          {Object.entries(relationship.dimensions).filter(([key]) => ["affection", "trust", "respect", "familiarity", "boundaries"].includes(key)).map(([key, value]) => <div className="relationMetric" key={key}><span>{dashboard.labels.relationships[key] ?? key}</span><progress max="100" value={Math.max(0, Math.min(100, value))}/><b>{value}</b></div>)}
          {relationship.tags.length > 0 && <p className="tagLine">{relationship.tags.join(" · ")}</p>}
        </article>) : <p className="studioHint">关系会从真实互动中逐渐形成。</p>}
      </section>}

      {railTab === "任务" && <section className="railPanel">
        <p className="eyebrow">当前任务</p>
        {dashboard?.quests.length ? dashboard.quests.map(quest => <article className="railCard" key={quest.key}><b>{quest.name}</b><span>{dashboard.labels.statuses[quest.status] ?? quest.status}</span></article>) : <p className="studioHint">当前没有公开任务。</p>}
        <h2 className="railSection">剧情进展</h2>
        {dashboard?.threads.map(thread => <article className="railCard" key={thread.key}><b>{thread.name}</b><span>阶段 {thread.stage} · {dashboard.labels.statuses[thread.status] ?? thread.status}</span>{thread.next_beat_hint && <small>{thread.next_beat_hint}</small>}</article>)}
      </section>}

      {railTab === "背包" && <section className="railPanel">
        <p className="eyebrow">持有物品</p>
        {dashboard?.inventory.length ? dashboard.inventory.map(item => <div className="statRow" key={item.key}><span>{item.name}</span><b>× {item.quantity}</b></div>) : <p className="studioHint">背包目前是空的。</p>}
        <h2 className="railSection">能力</h2>
        {dashboard?.abilities.length ? dashboard.abilities.map(ability => <div className="statRow" key={ability.key}><span>{ability.name}</span><b>{ability.mastery}</b></div>) : <p className="studioHint">尚未掌握可显示的能力。</p>}
      </section>}

      {railTab === "结局" && <section className="railPanel endingPanel">
        <p className="eyebrow">关系意愿</p>
        <p className="studioHint">这是明确选择，不会由好感数值或模型替你决定。拒绝恋爱后，角色仍可发展友情与个人故事。</p>
        {Object.entries(endingStatus?.leads ?? {}).map(([lead, name]) => <article className="consentCard" key={lead}><b>{name}</b><div className="consentButtons">
          <button disabled={completed} className={endingStatus?.consent[lead] === "accepted" ? "active" : ""} onClick={() => setConsent(lead, "accepted").catch(exception => setError(exception.message))}>愿意探索恋爱线</button>
          <button disabled={completed} className={endingStatus?.consent[lead] === "rejected" ? "active" : ""} onClick={() => setConsent(lead, "rejected").catch(exception => setError(exception.message))}>只做朋友</button>
          <button disabled={completed} className={endingStatus?.consent[lead] === "undecided" ? "active" : ""} onClick={() => setConsent(lead, "undecided").catch(exception => setError(exception.message))}>暂不决定</button>
        </div></article>)}
        <h2 className="railSection">可抵达的结局</h2>
        {endingStatus?.selected && <article className="selectedEnding"><span>已经抵达</span><b>{endingStatus.selected.title}</b></article>}
        {endingStatus?.endings.filter(ending => ending.available).map(ending => <button className="endingChoice" key={ending.key} disabled={completed} onClick={() => chooseEnding(ending).catch(exception => setError(exception.message))}><span>{ending.type === "romance" ? "恋爱" : ending.type === "bond" ? "羁绊" : "成长"}</span><b>{ending.title}</b></button>)}
        {!completed && !endingStatus?.endings.some(ending => ending.available) && <p className="studioHint">继续推进主线、建立关系或完成个人目标，新的结局会在满足条件后出现。</p>}
        {!!endingStatus?.hidden_count && <p className="hiddenEnding">还有 {endingStatus.hidden_count} 个未揭示的可能</p>}
      </section>}
    </aside>
  </div>;
}
