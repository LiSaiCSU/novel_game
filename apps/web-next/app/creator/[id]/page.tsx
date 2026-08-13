"use client";

import {useParams, useRouter} from "next/navigation";
import {FormEvent, useEffect, useMemo, useRef, useState} from "react";
import {api, ApiError} from "@/lib/api";

type Entity = Record<string, unknown> & {key: string; name?: string; title?: string; description?: string};
type Package = {
  manifest: {title: string; summary: string; rating: string; tags: string[]; theme: Record<string, string>; assets: AssetReference[]};
  content: {
    world: Record<string, unknown>;
    scenarios: Entity[];
    locations: Entity[];
    characters: Entity[];
    facts: Entity[];
    endings: EndingDefinition[];
    plot_threads: Entity[];
    quests: Entity[];
    rules: Array<Record<string, unknown>>;
    narrative: Record<string, unknown>;
  };
  author_tests?: Array<Record<string, unknown>>;
};
type Project = {id: string; title: string; revision: number; document: Package};
type ProjectRevision = {revision: number; created_at: string; diagnostics: Diagnostic[]; document: Package};
type Diagnostic = {level: string; message: string};
type Release = {id: string; version: string; visibility: string; status: string; checksum: string};
type CreatedRelease = {id: string; checksum: string; status: string; share_token?: string | null};
type AssetReference = {key: string; kind: "cover" | "avatar" | "background"; path: string; alt: string};
type Asset = AssetReference & {id: string; url: string; thumbnail_url?: string | null; width: number; height: number; byte_size: number; status: string};
type EndingDefinition = {key: string; title: string; type: "romance" | "bond" | "independent" | "other"; lead?: string | null; condition: unknown; requires_consent?: boolean; hidden_until_available?: boolean; priority?: number; epilogue: string};
type AuthorAssertionResult = {path: string; op: string; passed: boolean; expected: unknown; actual: unknown; message: string};
type AuthorTestResult = {key: string; name: string; passed: boolean; duration_ms: number; actions_run: number; assertions: AuthorAssertionResult[]; error: string};
type AuthorTestSuite = {passed: boolean; declared_tests: number; total: number; passed_count: number; failed_count: number; duration_ms: number; results: AuthorTestResult[]};

const tabs = ["概览", "世界与入口", "场景与地点", "人物", "事实与秘密", "任务与剧情线", "结局设计", "叙事风格", "规则", "玩法测试", "图片素材", "版本差异", "内容包", "发布中心"];
const clone = <T,>(value: T): T => structuredClone(value);

function Field({label, value, onChange, multiline = false}: {label: string; value: unknown; onChange: (value: string) => void; multiline?: boolean}) {
  return <label className="studioField"><span>{label}</span>{multiline
    ? <textarea className="textarea" value={String(value ?? "")} onChange={event => onChange(event.target.value)}/>
    : <input className="input" value={String(value ?? "")} onChange={event => onChange(event.target.value)}/>}</label>;
}

function EntityList({items, kind, onChange, fields}: {items: Entity[]; kind: string; onChange: (items: Entity[]) => void; fields: Array<[string, string, boolean?]>}) {
  function add() {
    const prefix: Record<string, string> = {地点: "location", 人物: "character", 事实: "fact", 剧情线: "plot_thread", 任务: "quest"};
    const key = `${prefix[kind] ?? "entity"}_${items.length + 1}`;
    onChange([...items, kind === "事实" ? {key, statement: `新${kind}`, sensitivity: 0} : {key, name: `新${kind}`, description: ""}]);
  }
  return <div className="entityWorkspace"><div className="entityToolbar"><p>{items.length} 项</p><button className="button" onClick={add}>添加{kind}</button></div>{items.length === 0 && <div className="empty"><p>还没有{kind}。从一个最重要的对象开始，系统会实时检查引用。</p></div>}{items.map((item, index) => <article className="entityCard" key={item.key}><header><code>{item.key}</code><button className="dangerLink" onClick={() => onChange(items.filter((_, i) => i !== index))}>删除</button></header><div className="formGrid">{fields.map(([key, label, multiline]) => <Field key={key} label={label} value={item[key]} multiline={multiline} onChange={value => {const next = clone(items); next[index][key] = ["age", "sensitivity"].includes(key) ? Number(value) : value; onChange(next)}}/>)}</div></article>)}</div>;
}

function JsonEditor({value, onApply, label}: {value: unknown; onApply: (value: unknown) => void; label: string}) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  return <textarea className="editor" aria-label={label} value={text} onChange={event => setText(event.target.value)} onBlur={() => {try {onApply(JSON.parse(text) as unknown)} catch { /* keep draft until valid */ }}}/>;
}

export default function Editor() {
  const {id} = useParams<{id: string}>();
  const router = useRouter();
  const [document, setDocument] = useState<Package>();
  const [tab, setTab] = useState("概览");
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]);
  const [releases, setReleases] = useState<Release[]>([]);
  const [revisions, setRevisions] = useState<ProjectRevision[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [testSuite, setTestSuite] = useState<AuthorTestSuite>();
  const [status, setStatus] = useState("正在载入项目");
  const [raw, setRaw] = useState("");
  const [shareUrl, setShareUrl] = useState("");
  const [history, setHistory] = useState<Package[]>([]);
  const [future, setFuture] = useState<Package[]>([]);
  const [conflict, setConflict] = useState<{revision: number; server: Package; local: Package}>();
  const [revisionNumber, setRevisionNumber] = useState(0);
  const revision = useRef(0);
  const editVersion = useRef(0);
  const dirty = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const saveChain = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    Promise.all([api<Project>(`/creator/projects/${id}`), api<Release[]>(`/creator/projects/${id}/releases`), api<Asset[]>(`/creator/projects/${id}/assets`), api<ProjectRevision[]>(`/creator/projects/${id}/revisions`)]).then(([loaded, versions, media, revisionHistory]) => {
      setDocument(loaded.document); setRaw(JSON.stringify(loaded.document, null, 2));
      revision.current = loaded.revision; setRevisionNumber(loaded.revision); setReleases(versions); setAssets(media); setRevisions(revisionHistory); setStatus("所有更改已保存");
    }).catch(error => setStatus(error.message));
  }, [id]);

  function save(next: Package): Promise<void> {
    const snapshot = clone(next);
    const snapshotVersion = editVersion.current;
    const operation = saveChain.current.catch(() => undefined).then(async () => {
      setStatus("正在自动保存…");
      try {
        const result = await api<{revision: number; diagnostics: Diagnostic[]}>(`/creator/projects/${id}/document`, {method: "PUT", body: JSON.stringify({expected_revision: revision.current, document: snapshot})});
        revision.current = result.revision;
        setRevisionNumber(result.revision);
        setDiagnostics(result.diagnostics);
        setRevisions(items => [{revision: result.revision, created_at: new Date().toISOString(), diagnostics: result.diagnostics, document: snapshot}, ...items.filter(item => item.revision !== result.revision)].slice(0, 50));
        if (snapshotVersion === editVersion.current) dirty.current = false;
        setStatus("所有更改已保存");
      } catch (error) {
        if (error instanceof ApiError && typeof error.problem.detail === "object" && error.problem.detail?.code === "revision_conflict") {
          const detail = error.problem.detail;
          setConflict({revision: Number(detail.revision), server: detail.document as Package, local: snapshot});
          setStatus("检测到并发修改：服务器版本与本地草稿都已保留，请选择处理方式");
        } else {
          setStatus(`未保存：${(error as Error).message}`);
        }
        throw error;
      }
    });
    saveChain.current = operation;
    return operation;
  }

  function change(mutator: (next: Package) => void) {
    if (!document) return;
    const next = clone(document); mutator(next);
    editVersion.current += 1; dirty.current = true;
    setHistory(items => [...items.slice(-29), clone(document)]); setFuture([]); setDocument(next); setRaw(JSON.stringify(next, null, 2));
    setStatus("等待自动保存"); clearTimeout(timer.current); timer.current = setTimeout(() => save(next), 900);
  }

  function undo() {const previous = history.at(-1); if (!previous || !document) return; clearTimeout(timer.current); editVersion.current += 1; dirty.current = true; setFuture(items => [clone(document), ...items]); setHistory(items => items.slice(0, -1)); setDocument(previous); setRaw(JSON.stringify(previous, null, 2)); void save(previous)}
  function redo() {const next = future[0]; if (!next || !document) return; clearTimeout(timer.current); editVersion.current += 1; dirty.current = true; setHistory(items => [...items, clone(document)]); setFuture(items => items.slice(1)); setDocument(next); setRaw(JSON.stringify(next, null, 2)); void save(next)}
  async function flushPendingSave() {clearTimeout(timer.current); await saveChain.current.catch(() => undefined); if (dirty.current && document) await save(document)}
  async function validate() {setStatus("正在编译并执行玩法测试…"); await flushPendingSave(); const result = await api<{valid: boolean; diagnostics: Diagnostic[]; checksum?: string; author_tests?: AuthorTestSuite | null}>(`/creator/projects/${id}/validate`, {method: "POST"}); setDiagnostics(result.diagnostics); setTestSuite(result.author_tests ?? undefined); setStatus(result.valid ? `校验与玩法测试通过 · ${result.checksum?.slice(0, 10)}` : "发现需要处理的问题"); return result.author_tests ?? undefined}
  async function createRelease(version: string, visibility: string) {await flushPendingSave(); const created = await api<CreatedRelease>(`/creator/projects/${id}/releases`, {method: "POST", body: JSON.stringify({version, visibility})}); setReleases(await api<Release[]>(`/creator/projects/${id}/releases`)); return created}
  async function appealRelease(releaseId: string) {const reason = window.prompt("请输入申诉理由（至少 10 个字符）。审核人员会看到此说明。"); if (!reason?.trim()) return; await api(`/creator/projects/${id}/releases/${releaseId}/appeal`, {method: "POST", body: JSON.stringify({reason: reason.trim()})}); setReleases(await api<Release[]>(`/creator/projects/${id}/releases`)); setStatus("申诉已提交，版本已重新进入审核队列")}
  async function shareDraft() {const result = await api<{share_token: string}>(`/creator/projects/${id}/share-token`, {method: "POST", body: JSON.stringify({rotate: true})}); const url = `${window.location.origin}/shared/${result.share_token}`; setShareUrl(url); await navigator.clipboard?.writeText(url); setStatus("只读分享链接已复制；再次生成会让旧链接失效")}
  async function uploadAsset(event: FormEvent<HTMLFormElement>) {event.preventDefault(); const form = new FormData(event.currentTarget); setStatus("正在清理图片元数据并生成安全制品…"); try {const asset = await api<Asset>(`/creator/projects/${id}/assets`, {method: "POST", body: form}); setAssets(items => [asset, ...items]); change(next => {next.manifest.assets = [...(next.manifest.assets ?? []).filter(item => item.key !== asset.key), {key: asset.key, kind: asset.kind, path: asset.path, alt: asset.alt}]}); event.currentTarget.reset()} catch (error) {setStatus(`素材上传失败：${(error as Error).message}`)}}
  async function preview() {setStatus("正在创建隔离预览…"); try {const release = await createRelease(`0.0.0-preview.${Date.now()}`, "private"); const play = await api<{id: string}>("/playthroughs", {method: "POST", body: JSON.stringify({release_id: release.id, name: "创作者预览", age: 20, gender: "female", preview: true})}); router.push(`/play/${play.id}`)} catch (error) {setStatus(`无法预览：${(error as Error).message}`)}}
  async function keepLocalConflict() {if (!conflict) return; revision.current = conflict.revision; setRevisionNumber(conflict.revision); const local = conflict.local; setConflict(undefined); await save(local)}
  function useServerConflict() {if (!conflict || !document) return; clearTimeout(timer.current); dirty.current = false; setHistory(items => [...items.slice(-29), clone(conflict.local)]); setFuture([]); setDocument(conflict.server); setRaw(JSON.stringify(conflict.server, null, 2)); revision.current = conflict.revision; setRevisionNumber(conflict.revision); setConflict(undefined); setStatus("已载入服务器版本；本地草稿保留在撤销历史中")}

  if (!document) return <main className="page"><div className="panel">{status}</div></main>;
  const world = document.content.world;
  const scenario = document.content.scenarios[0];
  return <div className="studio">
    <aside className="studioSide"><p className="eyebrow">创作项目</p><h2>{document.manifest.title}</h2><p className="saveState">{status}</p><div className="studioNav">{tabs.map(item => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item}</button>)}</div></aside>
    <section className="studioMain"><div className="pageHead"><div><p className="eyebrow">REVISION {revisionNumber}</p><h1>{tab}</h1></div><div className="toolbar"><button className="button" disabled={!history.length} onClick={undo}>撤销</button><button className="button" disabled={!future.length} onClick={redo}>重做</button><a className="button" href={`/api/v1/creator/projects/${id}/export?format=yaml`}>导出 YAML</a><button className="button" onClick={() => shareDraft().catch(error => setStatus(error.message))}>分享只读草稿</button><button className="button" onClick={validate}>完整校验</button><button className="button primary" onClick={preview}>预览试玩</button></div></div>{shareUrl && <div className="success shareUrl">{shareUrl}</div>}{conflict && <section className="conflictNotice" role="alert"><div><b>发现另一个编辑版本</b><p>服务器现在是 Revision {conflict.revision}。系统没有覆盖任一方内容。</p></div><button className="button primary" onClick={() => keepLocalConflict().catch(error => setStatus(error.message))}>把本地草稿保存为下一修订</button><button className="button" onClick={useServerConflict}>采用服务器版本</button></section>}
      {tab === "概览" && <div className="formGrid"><Field label="作品标题" value={document.manifest.title} onChange={value => change(next => next.manifest.title = value)}/><Field label="一句话简介" value={document.manifest.summary} multiline onChange={value => change(next => next.manifest.summary = value)}/><Field label="标签（逗号分隔）" value={document.manifest.tags.join(", ")} onChange={value => change(next => next.manifest.tags = value.split(",").map(item => item.trim()).filter(Boolean))}/><label className="studioField"><span>内容分级</span><select className="select" value={document.manifest.rating} onChange={event => change(next => next.manifest.rating = event.target.value)}><option>all</option><option>13+</option><option>16+</option><option>18+</option></select></label></div>}
      {tab === "世界与入口" && <div className="formGrid"><Field label="世界名称" value={world.name} onChange={value => change(next => next.content.world.name = value)}/><Field label="世界简介" value={world.description} multiline onChange={value => change(next => next.content.world.description = value)}/><Field label="入口标题" value={scenario?.title} onChange={value => change(next => next.content.scenarios[0].title = value)}/><Field label="开场前提" value={scenario?.premise} multiline onChange={value => change(next => next.content.scenarios[0].premise = value)}/><label className="studioField"><span>开场地点</span><select className="select" value={String(scenario?.start_location ?? "")} onChange={event => change(next => next.content.scenarios[0].start_location = event.target.value)}>{document.content.locations.map(item => <option key={item.key} value={item.key}>{item.name || item.key}</option>)}</select></label></div>}
      {tab === "场景与地点" && <LocationWorkspace items={document.content.locations} startLocation={String(scenario?.start_location ?? "")} onChange={items => change(next => next.content.locations = items)}/>} 
      {tab === "人物" && <EntityList kind="人物" items={document.content.characters} fields={[["name", "姓名"], ["age", "年龄"], ["location", "初始地点"], ["background", "背景与个人目标", true], ["secret", "秘密", true]]} onChange={items => change(next => next.content.characters = items)}/>} 
      {tab === "事实与秘密" && <KnowledgeStudio facts={document.content.facts} characters={document.content.characters} onChange={items => change(next => next.content.facts = items)}/>} 
      {tab === "任务与剧情线" && <><h2>剧情线</h2><EntityList kind="剧情线" items={document.content.plot_threads} fields={[["title", "标题"], ["description", "目标与冲突", true]]} onChange={items => change(next => next.content.plot_threads = items)}/><h2>任务</h2><EntityList kind="任务" items={document.content.quests} fields={[["title", "标题"], ["description", "完成条件", true], ["giver", "发布人物 key"], ["plot_thread", "所属剧情线 key"]]} onChange={items => change(next => next.content.quests = items)}/></>}
      {tab === "结局设计" && <EndingStudio endings={document.content.endings ?? []} characters={document.content.characters} onChange={items => change(next => next.content.endings = items)}/>} 
      {tab === "叙事风格" && <div className="formGrid"><Field label="基调" value={(document.content.narrative.style as Record<string, unknown> | undefined)?.tone} multiline onChange={value => change(next => {const style = (next.content.narrative.style ?? {}) as Record<string, unknown>; style.tone = value; next.content.narrative.style = style})}/><Field label="叙事指导" value={(document.content.narrative.style as Record<string, unknown> | undefined)?.guidance} multiline onChange={value => change(next => {const style = (next.content.narrative.style ?? {}) as Record<string, unknown>; style.guidance = value.split("\n").filter(Boolean); next.content.narrative.style = style})}/></div>}
      {tab === "规则" && <div><p className="studioHint">规则使用受限 AST，不执行 JavaScript、Python、文件或网络访问。编辑完成并离开输入区后应用。</p><JsonEditor key={JSON.stringify(document.content.rules)} label="声明式规则" value={document.content.rules} onApply={value => change(next => next.content.rules = value as Array<Record<string, unknown>>)}/></div>}
      {tab === "玩法测试" && <AuthorTestStudio tests={document.author_tests ?? []} suite={testSuite} onRun={validate} onChange={tests => {setTestSuite(undefined); change(next => next.author_tests = tests)}}/>}
      {tab === "图片素材" && <AssetManager assets={assets} upload={uploadAsset}/>} 
      {tab === "版本差异" && <VersionDiff revisions={revisions}/>} 
      {tab === "内容包" && <div><p className="studioHint">高级模式直接查看规范制品。粘贴内容后离开文本框才会应用，以免半段 JSON 覆盖有效版本。</p><textarea className="editor" value={raw} onChange={event => setRaw(event.target.value)} onBlur={() => {try {const parsed = JSON.parse(raw) as Package; change(next => Object.assign(next, parsed))} catch {setStatus("JSON 语法无效，未覆盖项目")}}}/></div>}
      {tab === "发布中心" && <ReleaseCenter releases={releases} publish={createRelease} appeal={appealRelease}/>} 
    </section>
    <aside className="studioInspect"><p className="eyebrow">实时诊断</p><h2>内容健康度</h2><div className="healthScore">{diagnostics.filter(item => item.level === "error").length ? "待修复" : "健康"}</div><div className="contentStats"><span>地点 <b>{document.content.locations.length}</b></span><span>人物 <b>{document.content.characters.length}</b></span><span>剧情线 <b>{document.content.plot_threads.length}</b></span><span>任务 <b>{document.content.quests.length}</b></span><span>事实 <b>{document.content.facts.length}</b></span><span>结局 <b>{document.content.endings?.length ?? 0}</b></span></div>{diagnostics.length === 0 ? <p className="studioHint">完整校验会检查悬空引用、地点可达性、规则类型、结局条件和发布兼容性。</p> : diagnostics.map((item, index) => <div className="diagnostic" key={index}><b>{item.level}</b><span>{item.message}</span></div>)}</aside>
  </div>;
}

function AuthorTestStudio({tests, suite, onChange, onRun}: {tests: Array<Record<string, unknown>>; suite?: AuthorTestSuite; onChange: (tests: Array<Record<string, unknown>>) => void; onRun: () => Promise<AuthorTestSuite | undefined>}) {
  const [running, setRunning] = useState(false);
  async function run() {
    setRunning(true);
    try {await onRun()} finally {setRunning(false)}
  }
  return <div className="authorTestWorkspace">
    <section className="panel stack">
      <div className="authorTestHead"><div><p className="eyebrow">DETERMINISTIC PLAYTESTS</p><h2>把关键承诺写成可重复测试</h2></div><button className="button primary" disabled={running} onClick={() => void run()}>{running ? "正在执行…" : "运行全部测试"}</button></div>
      <p className="studioHint">每条测试会创建隔离的内存存档，可预置玩家、关系、知识、任务与剧情线，再执行最多 20 个真实行动。测试不会调用外部模型，也不会读取文件、网络或数据库。公开发布至少需要一条声明测试。</p>
      <div className="authorTestEditor"><JsonEditor key={JSON.stringify(tests)} label="玩法测试定义" value={tests} onApply={value => onChange(value as Array<Record<string, unknown>>)}/></div>
    </section>
    <section className="authorTestResults" aria-live="polite">
      {!suite && <div className="empty"><h3>尚未运行</h3><p>先保存测试定义，再运行完整编译与玩法测试。失败结果会显示实际值与期望值。</p></div>}
      {suite && <div className={suite.passed ? "testSummary pass" : "testSummary fail"}><b>{suite.passed ? "全部通过" : `${suite.failed_count} 项失败`}</b><span>{suite.passed_count}/{suite.total} · {suite.duration_ms} ms · {suite.declared_tests} 条声明测试</span></div>}
      {suite?.results.map(test => <article className={`testCase ${test.passed ? "pass" : "fail"}`} key={test.key}>
        <header><div><b>{test.name}</b><code>{test.key}</code></div><span>{test.passed ? "PASS" : "FAIL"} · {test.duration_ms} ms · {test.actions_run} actions</span></header>
        {test.error && <p className="error">{test.error}</p>}
        {test.assertions.map((assertion, index) => <div className="testAssertion" key={`${assertion.path}-${index}`}><span className={assertion.passed ? "testPass" : "testFail"}>{assertion.passed ? "✓" : "×"}</span><code>{assertion.path} {assertion.op}</code>{!assertion.passed && <small>期望 {JSON.stringify(assertion.expected)}，实际 {JSON.stringify(assertion.actual)}</small>}</div>)}
      </article>)}
    </section>
  </div>;
}

function LocationWorkspace({items, startLocation, onChange}: {items: Entity[]; startLocation: string; onChange: (items: Entity[]) => void}) {
  const [from, setFrom] = useState(items[0]?.key ?? "");
  const [to, setTo] = useState(items[1]?.key ?? "");
  const [minutes, setMinutes] = useState(10);
  const positions = useMemo(() => Object.fromEntries(items.map((item, index) => [item.key, {x: 90 + (index % 3) * 250, y: 60 + Math.floor(index / 3) * 105}])), [items]);
  const edges = useMemo(() => {
    const found = new Map<string, {from: string; to: string; minutes: number}>();
    for (const item of items) {
      const travel = (item.travel ?? {}) as Record<string, unknown>;
      for (const [target, duration] of Object.entries(travel)) {
        if (!positions[target]) continue;
        const edgeKey = [item.key, target].sort().join("::");
        if (!found.has(edgeKey)) found.set(edgeKey, {from: item.key, to: target, minutes: Number(duration) || 0});
      }
    }
    return [...found.values()];
  }, [items, positions]);
  const height = Math.max(180, 125 + Math.ceil(items.length / 3) * 105);

  function connect() {
    if (!from || !to || from === to) return;
    const next = clone(items);
    for (const [source, target] of [[from, to], [to, from]]) {
      const item = next.find(entry => entry.key === source);
      if (!item) continue;
      item.travel = {...((item.travel ?? {}) as Record<string, unknown>), [target]: Math.max(1, minutes)};
    }
    onChange(next);
  }

  function disconnect(edge: {from: string; to: string}) {
    const next = clone(items);
    for (const [source, target] of [[edge.from, edge.to], [edge.to, edge.from]]) {
      const item = next.find(entry => entry.key === source);
      const travel = {...((item?.travel ?? {}) as Record<string, unknown>)};
      delete travel[target];
      if (item) item.travel = travel;
    }
    onChange(next);
  }

  return <div className="entityWorkspace">
    <section className="mapPanel"><header><div><p className="eyebrow">LOCATION GRAPH</p><h2>地点关系图</h2></div><span>{items.length} 个节点 · {edges.length} 条通路</span></header>
      {items.length ? <svg className="locationMap" viewBox={`0 0 760 ${height}`} role="img" aria-label="地点和双向通路关系图">
        {edges.map(edge => {const a = positions[edge.from], b = positions[edge.to]; return <g key={`${edge.from}-${edge.to}`}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y}/><text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 5}>{edge.minutes} 分</text></g>})}
        {items.map(item => {const point = positions[item.key]; return <g className={item.key === startLocation ? "startNode" : ""} key={item.key} transform={`translate(${point.x - 78} ${point.y - 25})`}><rect width="156" height="50" rx="12"/><text x="78" y="21" textAnchor="middle">{String(item.name ?? item.key).slice(0, 12)}</text><text className="nodeKey" x="78" y="38" textAnchor="middle">{item.key.slice(0, 20)}</text></g>})}
      </svg> : <div className="empty">添加地点后会在这里形成可达性图。</div>}
      <div className="connectionEditor"><select className="select" value={from} onChange={event => setFrom(event.target.value)}>{items.map(item => <option key={item.key} value={item.key}>{String(item.name ?? item.key)}</option>)}</select><span>⇄</span><select className="select" value={to} onChange={event => setTo(event.target.value)}>{items.map(item => <option key={item.key} value={item.key}>{String(item.name ?? item.key)}</option>)}</select><input className="input" aria-label="通行分钟" type="number" min="1" max="1440" value={minutes} onChange={event => setMinutes(Number(event.target.value))}/><button className="button" onClick={connect}>添加双向通路</button></div>
      <div className="edgeList">{edges.map(edge => <button key={`${edge.from}-${edge.to}`} onClick={() => disconnect(edge)} title="删除这条双向通路">{String(items.find(item => item.key === edge.from)?.name ?? edge.from)} ⇄ {String(items.find(item => item.key === edge.to)?.name ?? edge.to)} · {edge.minutes} 分 <span>×</span></button>)}</div>
    </section>
    <EntityList kind="地点" items={items} fields={[["name", "显示名称"], ["type", "地点类型"], ["parent", "父级地点 key"], ["description", "场景描述", true]]} onChange={onChange}/>
  </div>;
}

function KnowledgeStudio({facts, characters, onChange}: {facts: Entity[]; characters: Entity[]; onChange: (facts: Entity[]) => void}) {
  const actors = [{key: "player", name: "玩家"}, ...characters.map(character => ({key: character.key, name: String(character.name ?? character.key)}))];
  function knowledge(fact: Entity, actor: string) {
    const map = (fact.initial_knowledge ?? {}) as Record<string, Record<string, unknown>>;
    return String(map[actor]?.state ?? "UNKNOWN");
  }
  function setKnowledge(factIndex: number, actor: string, state: string) {
    const next = clone(facts);
    const map = {...((next[factIndex].initial_knowledge ?? {}) as Record<string, Record<string, unknown>>)};
    if (state === "UNKNOWN") delete map[actor];
    else map[actor] = {...(map[actor] ?? {}), state, confidence: state === "KNOWN" ? 1 : .6, source: map[actor]?.source ?? "DOCUMENT"};
    next[factIndex].initial_knowledge = map;
    onChange(next);
  }
  return <div className="entityWorkspace">
    <section className="knowledgePanel"><div className="entityToolbar"><div><p className="eyebrow">KNOWLEDGE BOUNDARIES</p><h2>知识与秘密矩阵</h2></div><p>未知 / 怀疑 / 已知</p></div>
      <p className="studioHint">这里定义开局时谁知道什么。运行时只会把角色已知的信息交给模型，秘密不会因为同处一个内容包而泄露。</p>
      <div className="knowledgeTable"><table><thead><tr><th>事实</th>{actors.map(actor => <th key={actor.key}>{actor.name}</th>)}</tr></thead><tbody>{facts.map((fact, factIndex) => <tr key={fact.key}><th title={String(fact.statement ?? fact.key)}>{String(fact.name ?? fact.statement ?? fact.key).slice(0, 22)}</th>{actors.map(actor => <td key={actor.key}><select aria-label={`${String(fact.statement ?? fact.key)}：${actor.name}`} value={knowledge(fact, actor.key)} onChange={event => setKnowledge(factIndex, actor.key, event.target.value)}><option value="UNKNOWN">未知</option><option value="SUSPECTED">怀疑</option><option value="KNOWN">已知</option></select></td>)}</tr>)}</tbody></table></div>
    </section>
    <EntityList kind="事实" items={facts} fields={[["statement", "事实内容", true], ["scope", "作用域"], ["sensitivity", "敏感度 0–1"]]} onChange={onChange}/>
  </div>;
}

function EndingStudio({endings, characters, onChange}: {endings: EndingDefinition[]; characters: Entity[]; onChange: (endings: EndingDefinition[]) => void}) {
  function add() {onChange([...endings, {key: `ending_${endings.length + 1}`, title: "新结局", type: "other", condition: false, hidden_until_available: true, priority: 0, epilogue: "请写下这个结局发生后的余韵。"}])}
  function update(index: number, patch: Partial<EndingDefinition>) {const next = clone(endings); next[index] = {...next[index], ...patch}; onChange(next)}
  return <div className="entityWorkspace"><div className="entityToolbar"><div><p className="studioHint">结局资格由受限条件 AST 对真实游戏状态判定，模型无法擅自发放结局。恋爱结局强制要求玩家明确同意。</p></div><button className="button" onClick={add}>添加结局</button></div>
    {endings.map((ending, index) => <article className="entityCard endingEditorCard" key={ending.key}><header><code>{ending.key}</code><button className="dangerLink" onClick={() => onChange(endings.filter((_, itemIndex) => itemIndex !== index))}>删除</button></header><div className="formGrid">
      <Field label="结局标题" value={ending.title} onChange={value => update(index, {title: value})}/>
      <label className="studioField"><span>类型</span><select className="select" value={ending.type} onChange={event => {const type = event.target.value as EndingDefinition["type"]; update(index, {type, requires_consent: type === "romance" ? true : ending.requires_consent})}}><option value="romance">恋爱</option><option value="bond">深度羁绊</option><option value="independent">独立成长</option><option value="other">其他</option></select></label>
      <label className="studioField"><span>关联人物</span><select className="select" value={ending.lead ?? ""} onChange={event => update(index, {lead: event.target.value || null})}><option value="">无</option>{characters.map(character => <option key={character.key} value={character.key}>{String(character.name ?? character.key)}</option>)}</select></label>
      <Field label="优先级" value={ending.priority ?? 0} onChange={value => update(index, {priority: Number(value)})}/>
      <label className="checkField"><input type="checkbox" checked={ending.requires_consent ?? false} disabled={ending.type === "romance"} onChange={event => update(index, {requires_consent: event.target.checked})}/>需要明确关系同意</label>
      <label className="checkField"><input type="checkbox" checked={ending.hidden_until_available ?? true} onChange={event => update(index, {hidden_until_available: event.target.checked})}/>达成前隐藏标题</label>
      <Field label="结局尾声" value={ending.epilogue} multiline onChange={value => update(index, {epilogue: value})}/>
      <label className="studioField conditionField"><span>达成条件（受限表达式 AST）</span><JsonEditor label={`${ending.title}达成条件`} value={ending.condition} onApply={value => update(index, {condition: value})}/></label>
    </div></article>)}
    {!endings.length && <div className="empty">还没有结局。至少设计一个独立成长结局，让恋爱选择不是完成作品的前提。</div>}
  </div>;
}

type FlatDocument = Record<string, string>;
function flattenDocument(value: unknown, path = "", target: FlatDocument = {}): FlatDocument {
  if (value !== null && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) flattenDocument(child, path ? `${path}.${key}` : key, target);
  } else target[path] = JSON.stringify(value) ?? "undefined";
  return target;
}

function VersionDiff({revisions}: {revisions: ProjectRevision[]}) {
  const [before, setBefore] = useState<number>();
  const [after, setAfter] = useState<number>();
  const beforeRevision = before ?? revisions[1]?.revision ?? revisions[0]?.revision;
  const afterRevision = after ?? revisions[0]?.revision;
  const changes = useMemo(() => {
    const oldDocument = revisions.find(item => item.revision === beforeRevision)?.document;
    const newDocument = revisions.find(item => item.revision === afterRevision)?.document;
    if (!oldDocument || !newDocument) return [];
    const oldFlat = flattenDocument(oldDocument), newFlat = flattenDocument(newDocument);
    return [...new Set([...Object.keys(oldFlat), ...Object.keys(newFlat)])].filter(path => oldFlat[path] !== newFlat[path]).map(path => ({path, before: oldFlat[path], after: newFlat[path]}));
  }, [revisions, beforeRevision, afterRevision]);
  if (!revisions.length) return <div className="empty">保存第一次修改后即可比较版本。</div>;
  return <div className="diffWorkspace"><section className="panel"><div className="diffSelectors"><label className="studioField"><span>对比起点</span><select className="select" value={beforeRevision} onChange={event => setBefore(Number(event.target.value))}>{revisions.map(item => <option key={item.revision} value={item.revision}>Revision {item.revision} · {new Date(item.created_at).toLocaleString("zh-CN")}</option>)}</select></label><span>→</span><label className="studioField"><span>对比终点</span><select className="select" value={afterRevision} onChange={event => setAfter(Number(event.target.value))}>{revisions.map(item => <option key={item.revision} value={item.revision}>Revision {item.revision} · {new Date(item.created_at).toLocaleString("zh-CN")}</option>)}</select></label></div></section>
    <div className="diffSummary"><b>{changes.length}</b><span>处字段变化</span></div>
    {changes.slice(0, 120).map(change => <article className="diffRow" key={change.path}><code>{change.path}</code><div><del>{change.before ?? "未设置"}</del><ins>{change.after ?? "已删除"}</ins></div></article>)}
    {changes.length > 120 && <p className="studioHint">仅显示前 120 处变化；导出两个版本可进行完整机器比较。</p>}
    {!changes.length && <div className="empty">两个修订内容一致。</div>}
  </div>;
}

function AssetManager({assets, upload}: {assets: Asset[]; upload: (event: FormEvent<HTMLFormElement>) => Promise<void>}) {
  return <div className="releaseLayout"><form className="panel stack" onSubmit={upload}><h2>上传图片</h2><label className="studioField"><span>稳定 key</span><input className="input" name="key" pattern="[a-z][a-z0-9_]{1,79}" placeholder="main_cover" required/></label><label className="studioField"><span>类型</span><select className="select" name="kind"><option value="cover">封面</option><option value="avatar">角色头像</option><option value="background">场景背景</option></select></label><label className="studioField"><span>无障碍描述</span><input className="input" name="alt_text" required maxLength={300}/></label><input className="input" type="file" name="file" accept="image/jpeg,image/png,image/webp" required/><button className="button primary">上传并加入内容包</button><p className="studioHint">支持 JPEG、PNG、WebP，最大 8 MB、64–6000 像素；服务端会重新编码、清除元数据并生成 WebP 缩略图。</p></form><section><h2>素材库</h2><div className="assetGrid">{assets.map(asset => <article className="assetCard" key={asset.id}><div className="assetPreview" role="img" aria-label={asset.alt} style={{backgroundImage: `url(${asset.thumbnail_url ?? asset.url})`}}/><b>{asset.key}</b><small>{asset.kind} · {asset.width}×{asset.height}</small></article>)}</div>{assets.length === 0 && <div className="empty">尚未上传图片</div>}</section></div>;
}

function ReleaseCenter({releases, publish, appeal}: {releases: Release[]; publish: (version: string, visibility: string) => Promise<CreatedRelease>; appeal: (releaseId: string) => Promise<void>}) {
  const [version, setVersion] = useState("1.0.0"); const [visibility, setVisibility] = useState("private"); const [message, setMessage] = useState("");
  return <div className="releaseLayout"><section className="panel stack"><h2>生成不可变版本</h2><Field label="语义版本" value={version} onChange={setVersion}/><label className="studioField"><span>可见性</span><select className="select" value={visibility} onChange={event => setVisibility(event.target.value)}><option value="private">私密</option><option value="unlisted">未列出</option><option value="public">公开并提交审核</option></select></label><button className="button primary" onClick={() => publish(version, visibility).then(async created => {if (created.share_token) {const url = `${window.location.origin}/invite/${created.share_token}`; await navigator.clipboard?.writeText(url); setMessage(`受邀链接已复制（令牌仅显示一次）：${url}`)} else setMessage("版本已创建")}).catch(error => setMessage(error.message))}>编译并发布</button>{message && <p className="saveState shareUrl">{message}</p>}</section><section><h2>版本历史</h2>{releases.length === 0 ? <div className="empty">尚未发布版本</div> : releases.map(item => <article className="releaseRow" key={item.id}><div><b>v{item.version}</b><small>{item.checksum.slice(0, 12)}</small></div><div className="releaseStatus"><span>{item.visibility} · {item.status}</span>{["rejected", "withdrawn"].includes(item.status) && <button className="dangerLink" onClick={() => appeal(item.id).then(() => setMessage("申诉已提交")).catch(error => setMessage(error.message))}>提交申诉</button>}</div></article>)}</section></div>;
}
