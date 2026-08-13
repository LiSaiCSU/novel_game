"use client";

import {CSSProperties, FormEvent, useEffect, useState} from "react";
import {useRouter} from "next/navigation";
import {api} from "@/lib/api";

type PlayerField = {key: string; label: string; type: "text" | "integer" | "choice" | "tags"; required: boolean; default?: string | number | string[]; minimum?: number; maximum?: number; choices: Array<{value: string; label: string}>};
type Release = {id: string; title: string; summary: string; premise: string; rating: string; tags: string[]; theme: {accent?: string}; player_fields: PlayerField[]; player_constraints: {gender?: string}; content_counts: {locations: number; characters: number; plot_threads: number; quests: number}};
type Credential = {provider: string; model: string};

export function ReleaseDetail({endpoint, shareToken}: {endpoint: string; shareToken?: string}) {
  const router = useRouter();
  const [work, setWork] = useState<Release>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  useEffect(() => {api<Release>(endpoint).then(setWork).catch(exception => setError(exception.message)); api<Credential[]>("/settings/llm-credentials").then(setCredentials).catch(() => undefined)}, [endpoint]);

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!work) return; setBusy(true); setError("");
    const data = new FormData(event.currentTarget); const playerConfig: Record<string, unknown> = {};
    const modelMode = String(data.get("model_mode") ?? "platform"); playerConfig.model_mode = modelMode;
    if (modelMode.startsWith("byok:")) {playerConfig.model_mode = "byok"; playerConfig.provider = modelMode.slice(5)}
    for (const field of work.player_fields) {if (["name", "age", "background"].includes(field.key)) continue; const raw = String(data.get(field.key) ?? ""); playerConfig[field.key] = field.type === "tags" ? raw.split(/[，,]/).map(item => item.trim()).filter(Boolean) : raw}
    try {const play = await api<{id: string}>("/playthroughs", {method: "POST", body: JSON.stringify({release_id: work.id, share_token: shareToken, name: String(data.get("name") ?? "旅行者"), age: Number(data.get("age") || 18), gender: work.player_constraints.gender ?? "unspecified", background: String(data.get("background") ?? ""), player_config: playerConfig})}); router.push(`/play/${play.id}`)} catch (exception) {setError((exception as Error).message)} finally {setBusy(false)}
  }

  if (error && !work) return <main className="page"><p className="error">{error}</p></main>;
  if (!work) return <main className="page">正在打开作品…</main>;
  const theme = {"--work-accent": work.theme.accent ?? "var(--rose)"} as CSSProperties;
  const fields = work.player_fields.length ? work.player_fields : [{key: "name", label: "姓名", type: "text", required: true, choices: []}, {key: "age", label: "年龄", type: "integer", required: true, default: 18, minimum: 18, maximum: 80, choices: []}] as PlayerField[];
  const countLabels: Array<[keyof Release["content_counts"], string]> = [["locations", "可探索地点"], ["characters", "重要人物"], ["plot_threads", "剧情线"], ["quests", "任务"]];
  return <main className="page workDetail" style={theme}><section className="workHero"><div className="workMonogram" aria-hidden="true">{work.title.slice(0, 1)}</div><div><p className="eyebrow">{shareToken ? "受邀作品" : "互动叙事"} · {work.rating}</p><h1>{work.title}</h1><p>{work.summary}</p><div className="chips">{work.tags.map(tag => <span key={tag}>{tag}</span>)}</div></div></section><div className="workDetailGrid"><section className="panel"><p className="eyebrow">故事前提</p><h2>进入这个世界之前</h2><p className="premise">{work.premise || work.summary}</p><div className="workStats">{countLabels.map(([key, label]) => <article key={key}><b>{work.content_counts[key]}</b><span>{label}</span></article>)}</div></section><form className="panel stack" onSubmit={start}><div><p className="eyebrow">创建角色</p><h2>让故事认识你</h2></div>{fields.map(field => <PlayerInput field={field} key={field.key}/>)}<label className="field"><span>叙事模型</span><select className="select" name="model_mode"><option value="platform">平台额度（推荐）</option>{credentials.map(item => <option value={`byok:${item.provider}`} key={item.provider}>我的 {item.provider} · {item.model}</option>)}</select></label>{error && <p className="error">{error}</p>}<button className="button primary" disabled={busy}>{busy ? "世界正在展开…" : "开始故事"}</button></form></div></main>;
}

function PlayerInput({field}: {field: PlayerField}) {
  const common = {id: field.key, name: field.key, required: field.required};
  if (field.type === "choice") return <label className="field"><span>{field.label}</span><select className="select" {...common} defaultValue={String(field.default ?? field.choices[0]?.value ?? "")}>{field.choices.map(choice => <option value={choice.value} key={choice.value}>{choice.label}</option>)}</select></label>;
  if (field.type === "integer") return <label className="field"><span>{field.label}</span><input className="input" type="number" {...common} min={field.minimum} max={field.maximum} defaultValue={Number(field.default ?? field.minimum ?? 18)}/></label>;
  if (field.key === "background") return <label className="field"><span>{field.label}</span><textarea className="textarea" {...common} defaultValue={String(field.default ?? "")}/></label>;
  return <label className="field"><span>{field.label}</span><input className="input" {...common} defaultValue={Array.isArray(field.default) ? field.default.join("，") : String(field.default ?? "")} placeholder={field.type === "tags" ? "用逗号分隔多个选项" : ""}/></label>;
}
