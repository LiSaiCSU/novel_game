"use client";

import { AlertTriangle, ArrowLeft, CheckCircle2, PanelRightOpen, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { AuthorTestStudio } from "./author-test-studio";
import { EntityList, Field, JsonEditor } from "./editor-controls";
import {
  clone,
  tabs,
  type Asset,
  type AuthorTestSuite,
  type CreatedRelease,
  type Diagnostic,
  type Package,
  type Project,
  type ProjectRevision,
  type Release,
} from "./editor-types";
import { AssetManager, ReleaseCenter, VersionDiff } from "./project-operations";
import { EndingStudio, KnowledgeStudio, LocationWorkspace } from "./world-studios";

export default function Editor() {
  const { id } = useParams<{ id: string }>();
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
  const [conflict, setConflict] = useState<{ revision: number; server: Package; local: Package }>();
  const [revisionNumber, setRevisionNumber] = useState(0);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const revision = useRef(0);
  const editVersion = useRef(0);
  const dirty = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const saveChain = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    Promise.all([
      api<Project>(`/creator/projects/${id}`),
      api<Release[]>(`/creator/projects/${id}/releases`),
      api<Asset[]>(`/creator/projects/${id}/assets`),
      api<ProjectRevision[]>(`/creator/projects/${id}/revisions`),
    ])
      .then(([loaded, versions, media, revisionHistory]) => {
        setDocument(loaded.document);
        setRaw(JSON.stringify(loaded.document, null, 2));
        revision.current = loaded.revision;
        setRevisionNumber(loaded.revision);
        setReleases(versions);
        setAssets(media);
        setRevisions(revisionHistory);
        setStatus("所有更改已保存");
      })
      .catch((error) => setStatus(error.message));
  }, [id]);

  function save(next: Package): Promise<void> {
    const snapshot = clone(next);
    const snapshotVersion = editVersion.current;
    const operation = saveChain.current
      .catch(() => undefined)
      .then(async () => {
        setStatus("正在自动保存…");
        try {
          const result = await api<{ revision: number; diagnostics: Diagnostic[] }>(
            `/creator/projects/${id}/document`,
            {
              method: "PUT",
              body: JSON.stringify({ expected_revision: revision.current, document: snapshot }),
            },
          );
          revision.current = result.revision;
          setRevisionNumber(result.revision);
          setDiagnostics(result.diagnostics);
          setRevisions((items) =>
            [
              {
                revision: result.revision,
                created_at: new Date().toISOString(),
                diagnostics: result.diagnostics,
                document: snapshot,
              },
              ...items.filter((item) => item.revision !== result.revision),
            ].slice(0, 50),
          );
          if (snapshotVersion === editVersion.current) dirty.current = false;
          setStatus("所有更改已保存");
        } catch (error) {
          if (
            error instanceof ApiError &&
            typeof error.problem.detail === "object" &&
            error.problem.detail?.code === "revision_conflict"
          ) {
            const detail = error.problem.detail;
            setConflict({
              revision: Number(detail.revision),
              server: detail.document as Package,
              local: snapshot,
            });
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
    const next = clone(document);
    mutator(next);
    editVersion.current += 1;
    dirty.current = true;
    setHistory((items) => [...items.slice(-29), clone(document)]);
    setFuture([]);
    setDocument(next);
    setRaw(JSON.stringify(next, null, 2));
    setStatus("等待自动保存");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => save(next), 900);
  }

  function undo() {
    const previous = history.at(-1);
    if (!previous || !document) return;
    clearTimeout(timer.current);
    editVersion.current += 1;
    dirty.current = true;
    setFuture((items) => [clone(document), ...items]);
    setHistory((items) => items.slice(0, -1));
    setDocument(previous);
    setRaw(JSON.stringify(previous, null, 2));
    void save(previous);
  }
  function redo() {
    const next = future[0];
    if (!next || !document) return;
    clearTimeout(timer.current);
    editVersion.current += 1;
    dirty.current = true;
    setHistory((items) => [...items, clone(document)]);
    setFuture((items) => items.slice(1));
    setDocument(next);
    setRaw(JSON.stringify(next, null, 2));
    void save(next);
  }
  async function flushPendingSave() {
    clearTimeout(timer.current);
    await saveChain.current.catch(() => undefined);
    if (dirty.current && document) await save(document);
  }
  async function validate() {
    setStatus("正在编译并执行玩法测试…");
    await flushPendingSave();
    const result = await api<{
      valid: boolean;
      diagnostics: Diagnostic[];
      checksum?: string;
      author_tests?: AuthorTestSuite | null;
    }>(`/creator/projects/${id}/validate`, { method: "POST" });
    setDiagnostics(result.diagnostics);
    setTestSuite(result.author_tests ?? undefined);
    setStatus(
      result.valid ? `校验与玩法测试通过 · ${result.checksum?.slice(0, 10)}` : "发现需要处理的问题",
    );
    return result.author_tests ?? undefined;
  }
  async function createRelease(version: string, visibility: string) {
    await flushPendingSave();
    const created = await api<CreatedRelease>(`/creator/projects/${id}/releases`, {
      method: "POST",
      body: JSON.stringify({ version, visibility }),
    });
    setReleases(await api<Release[]>(`/creator/projects/${id}/releases`));
    return created;
  }
  async function appealRelease(releaseId: string) {
    const reason = window.prompt("请输入申诉理由（至少 10 个字符）。审核人员会看到此说明。");
    if (!reason?.trim()) return;
    await api(`/creator/projects/${id}/releases/${releaseId}/appeal`, {
      method: "POST",
      body: JSON.stringify({ reason: reason.trim() }),
    });
    setReleases(await api<Release[]>(`/creator/projects/${id}/releases`));
    setStatus("申诉已提交，版本已重新进入审核队列");
  }
  async function shareDraft() {
    const result = await api<{ share_token: string }>(`/creator/projects/${id}/share-token`, {
      method: "POST",
      body: JSON.stringify({ rotate: true }),
    });
    const url = `${window.location.origin}/shared/${result.share_token}`;
    setShareUrl(url);
    await navigator.clipboard?.writeText(url);
    setStatus("只读分享链接已复制；再次生成会让旧链接失效");
  }
  async function uploadAsset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setStatus("正在清理图片元数据并生成安全制品…");
    try {
      const asset = await api<Asset>(`/creator/projects/${id}/assets`, {
        method: "POST",
        body: form,
      });
      setAssets((items) => [asset, ...items]);
      change((next) => {
        next.manifest.assets = [
          ...(next.manifest.assets ?? []).filter((item) => item.key !== asset.key),
          { key: asset.key, kind: asset.kind, path: asset.path, alt: asset.alt },
        ];
      });
      event.currentTarget.reset();
    } catch (error) {
      setStatus(`素材上传失败：${(error as Error).message}`);
    }
  }
  async function preview() {
    setStatus("正在创建隔离预览…");
    try {
      const release = await createRelease(`0.0.0-preview.${Date.now()}`, "private");
      const play = await api<{ id: string }>("/playthroughs", {
        method: "POST",
        body: JSON.stringify({
          release_id: release.id,
          name: "创作者预览",
          age: 20,
          gender: "female",
          preview: true,
        }),
      });
      router.push(`/play/${play.id}`);
    } catch (error) {
      setStatus(`无法预览：${(error as Error).message}`);
    }
  }
  async function keepLocalConflict() {
    if (!conflict) return;
    revision.current = conflict.revision;
    setRevisionNumber(conflict.revision);
    const local = conflict.local;
    setConflict(undefined);
    await save(local);
  }
  function useServerConflict() {
    if (!conflict || !document) return;
    clearTimeout(timer.current);
    dirty.current = false;
    setHistory((items) => [...items.slice(-29), clone(conflict.local)]);
    setFuture([]);
    setDocument(conflict.server);
    setRaw(JSON.stringify(conflict.server, null, 2));
    revision.current = conflict.revision;
    setRevisionNumber(conflict.revision);
    setConflict(undefined);
    setStatus("已载入服务器版本；本地草稿保留在撤销历史中");
  }

  if (!document)
    return (
      <div className="page">
        <div className="panel">{status}</div>
      </div>
    );
  const world = document.content.world;
  const scenario = document.content.scenarios[0];
  const errorCount = diagnostics.filter((item) => item.level === "error").length;
  const statusTone = status.startsWith("未保存") || status.startsWith("无法") ? "failed" : "saved";
  const tabCounts: Record<string, number | undefined> = {
    场景与地点: document.content.locations.length,
    人物: document.content.characters.length,
    事实与秘密: document.content.facts.length,
    任务与剧情线: document.content.plot_threads.length + document.content.quests.length,
    结局设计: document.content.endings?.length ?? 0,
    图片素材: assets.length,
    版本差异: revisions.length,
    发布中心: releases.length,
  };
  return (
    <div className="studio">
      <aside className="studioSide">
        <Link className="studioBack" href="/creator">
          <ArrowLeft size={15} /> 返回项目
        </Link>
        <p className="eyebrow">创作项目</p>
        <h2>{document.manifest.title}</h2>
        <p className={`saveState ${statusTone}`} role="status" aria-live="polite">
          {statusTone === "failed" ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
          <span>{status}</span>
        </p>
        <nav className="studioNav" aria-label="项目编辑栏目">
          {tabs.map((item) => (
            <button
              type="button"
              key={item}
              className={tab === item ? "active" : ""}
              onClick={() => setTab(item)}
            >
              <span>{item}</span>
              {tabCounts[item] !== undefined && <small>{tabCounts[item]}</small>}
            </button>
          ))}
        </nav>
      </aside>
      <section className="studioMain">
        <div className="pageHead studioHead">
          <div>
            <p className="eyebrow">修订版本 {revisionNumber}</p>
            <h1>{tab}</h1>
          </div>
          <div className="toolbar studioToolbar">
            <button className="button" disabled={!history.length} onClick={undo}>
              撤销
            </button>
            <button className="button" disabled={!future.length} onClick={redo}>
              重做
            </button>
            <a className="button" href={`/api/v1/creator/projects/${id}/export?format=yaml`}>
              导出 YAML
            </a>
            <button
              className="button"
              onClick={() => shareDraft().catch((error) => setStatus(error.message))}
            >
              分享只读草稿
            </button>
            <button className="button" onClick={validate}>
              完整校验
            </button>
            <button
              className="button inspectorTrigger"
              type="button"
              aria-expanded={inspectorOpen}
              onClick={() => setInspectorOpen(true)}
            >
              <PanelRightOpen size={16} />
              诊断 {errorCount > 0 && <span className="notificationCount">{errorCount}</span>}
            </button>
            <button className="button primary" onClick={preview}>
              预览试玩
            </button>
          </div>
        </div>
        {shareUrl && <div className="success shareUrl">{shareUrl}</div>}
        {conflict && (
          <section className="conflictNotice" role="alert">
            <div>
              <b>发现另一个编辑版本</b>
              <p>服务器现在是 Revision {conflict.revision}。系统没有覆盖任一方内容。</p>
            </div>
            <button
              className="button primary"
              onClick={() => keepLocalConflict().catch((error) => setStatus(error.message))}
            >
              把本地草稿保存为下一修订
            </button>
            <button className="button" onClick={useServerConflict}>
              采用服务器版本
            </button>
          </section>
        )}
        {tab === "概览" && (
          <div className="formGrid">
            <Field
              label="作品标题"
              value={document.manifest.title}
              onChange={(value) => change((next) => (next.manifest.title = value))}
            />
            <Field
              label="一句话简介"
              value={document.manifest.summary}
              multiline
              onChange={(value) => change((next) => (next.manifest.summary = value))}
            />
            <Field
              label="标签（逗号分隔）"
              value={document.manifest.tags.join(", ")}
              onChange={(value) =>
                change(
                  (next) =>
                    (next.manifest.tags = value
                      .split(",")
                      .map((item) => item.trim())
                      .filter(Boolean)),
                )
              }
            />
            <label className="studioField">
              <span>内容分级</span>
              <select
                className="select"
                value={document.manifest.rating}
                onChange={(event) => change((next) => (next.manifest.rating = event.target.value))}
              >
                <option>all</option>
                <option>13+</option>
                <option>16+</option>
                <option>18+</option>
              </select>
            </label>
          </div>
        )}
        {tab === "世界与入口" && (
          <div className="formGrid">
            <Field
              label="世界名称"
              value={world.name}
              onChange={(value) => change((next) => (next.content.world.name = value))}
            />
            <Field
              label="世界简介"
              value={world.description}
              multiline
              onChange={(value) => change((next) => (next.content.world.description = value))}
            />
            <Field
              label="入口标题"
              value={scenario?.title}
              onChange={(value) => change((next) => (next.content.scenarios[0].title = value))}
            />
            <Field
              label="开场前提"
              value={scenario?.premise}
              multiline
              onChange={(value) => change((next) => (next.content.scenarios[0].premise = value))}
            />
            <label className="studioField">
              <span>开场地点</span>
              <select
                className="select"
                value={String(scenario?.start_location ?? "")}
                onChange={(event) =>
                  change((next) => (next.content.scenarios[0].start_location = event.target.value))
                }
              >
                {document.content.locations.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.name || item.key}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        {tab === "场景与地点" && (
          <LocationWorkspace
            items={document.content.locations}
            startLocation={String(scenario?.start_location ?? "")}
            onChange={(items) => change((next) => (next.content.locations = items))}
          />
        )}
        {tab === "人物" && (
          <EntityList
            kind="人物"
            items={document.content.characters}
            fields={[
              ["name", "姓名"],
              ["age", "年龄"],
              ["location", "初始地点"],
              ["background", "背景与个人目标", true],
              ["secret", "秘密", true],
            ]}
            onChange={(items) => change((next) => (next.content.characters = items))}
          />
        )}
        {tab === "事实与秘密" && (
          <KnowledgeStudio
            facts={document.content.facts}
            characters={document.content.characters}
            onChange={(items) => change((next) => (next.content.facts = items))}
          />
        )}
        {tab === "任务与剧情线" && (
          <>
            <h2>剧情线</h2>
            <EntityList
              kind="剧情线"
              items={document.content.plot_threads}
              fields={[
                ["title", "标题"],
                ["description", "目标与冲突", true],
              ]}
              onChange={(items) => change((next) => (next.content.plot_threads = items))}
            />
            <h2>任务</h2>
            <EntityList
              kind="任务"
              items={document.content.quests}
              fields={[
                ["title", "标题"],
                ["description", "完成条件", true],
                ["giver", "发布人物 key"],
                ["plot_thread", "所属剧情线 key"],
              ]}
              onChange={(items) => change((next) => (next.content.quests = items))}
            />
          </>
        )}
        {tab === "结局设计" && (
          <EndingStudio
            endings={document.content.endings ?? []}
            characters={document.content.characters}
            onChange={(items) => change((next) => (next.content.endings = items))}
          />
        )}
        {tab === "叙事风格" && (
          <div className="formGrid">
            <Field
              label="基调"
              value={
                (document.content.narrative.style as Record<string, unknown> | undefined)?.tone
              }
              multiline
              onChange={(value) =>
                change((next) => {
                  const style = (next.content.narrative.style ?? {}) as Record<string, unknown>;
                  style.tone = value;
                  next.content.narrative.style = style;
                })
              }
            />
            <Field
              label="叙事指导"
              value={
                (document.content.narrative.style as Record<string, unknown> | undefined)?.guidance
              }
              multiline
              onChange={(value) =>
                change((next) => {
                  const style = (next.content.narrative.style ?? {}) as Record<string, unknown>;
                  style.guidance = value.split("\n").filter(Boolean);
                  next.content.narrative.style = style;
                })
              }
            />
          </div>
        )}
        {tab === "规则" && (
          <div>
            <p className="studioHint">
              规则使用受限 AST，不执行
              JavaScript、Python、文件或网络访问。编辑完成并离开输入区后应用。
            </p>
            <JsonEditor
              key={JSON.stringify(document.content.rules)}
              label="声明式规则"
              value={document.content.rules}
              onApply={(value) =>
                change((next) => (next.content.rules = value as Array<Record<string, unknown>>))
              }
            />
          </div>
        )}
        {tab === "玩法测试" && (
          <AuthorTestStudio
            tests={document.author_tests ?? []}
            suite={testSuite}
            onRun={validate}
            onChange={(tests) => {
              setTestSuite(undefined);
              change((next) => (next.author_tests = tests));
            }}
          />
        )}
        {tab === "图片素材" && <AssetManager assets={assets} upload={uploadAsset} />}
        {tab === "版本差异" && <VersionDiff revisions={revisions} />}
        {tab === "内容包" && (
          <div>
            <p className="studioHint">
              高级模式直接查看规范制品。粘贴内容后离开文本框才会应用，以免半段 JSON 覆盖有效版本。
            </p>
            <textarea
              className="editor"
              value={raw}
              onChange={(event) => setRaw(event.target.value)}
              onBlur={() => {
                try {
                  const parsed = JSON.parse(raw) as Package;
                  change((next) => Object.assign(next, parsed));
                } catch {
                  setStatus("JSON 语法无效，未覆盖项目");
                }
              }}
            />
          </div>
        )}
        {tab === "发布中心" && (
          <ReleaseCenter releases={releases} publish={createRelease} appeal={appealRelease} />
        )}
      </section>
      {inspectorOpen && (
        <button
          className="inspectorBackdrop"
          type="button"
          aria-label="关闭诊断面板"
          onClick={() => setInspectorOpen(false)}
        />
      )}
      <aside className={`studioInspect ${inspectorOpen ? "open" : ""}`} aria-label="实时诊断">
        <button
          className="inspectorClose"
          type="button"
          aria-label="关闭诊断面板"
          onClick={() => setInspectorOpen(false)}
        >
          <X size={18} />
        </button>
        <DiagnosticsPanel document={document} diagnostics={diagnostics} />
      </aside>
    </div>
  );
}

function DiagnosticsPanel({
  document,
  diagnostics,
}: {
  document: Package;
  diagnostics: Diagnostic[];
}) {
  const errorCount = diagnostics.filter((item) => item.level === "error").length;
  return (
    <>
      <p className="eyebrow">实时诊断</p>
      <h2>内容健康度</h2>
      <div className={`healthScore ${errorCount ? "attention" : ""}`}>
        {errorCount ? `${errorCount} 项待修复` : "结构健康"}
      </div>
      <div className="contentStats">
        <span>
          地点 <b>{document.content.locations.length}</b>
        </span>
        <span>
          人物 <b>{document.content.characters.length}</b>
        </span>
        <span>
          剧情线 <b>{document.content.plot_threads.length}</b>
        </span>
        <span>
          任务 <b>{document.content.quests.length}</b>
        </span>
        <span>
          事实 <b>{document.content.facts.length}</b>
        </span>
        <span>
          结局 <b>{document.content.endings?.length ?? 0}</b>
        </span>
      </div>
      {diagnostics.length === 0 ? (
        <p className="studioHint">
          完整校验会检查悬空引用、地点可达性、规则类型、结局条件和发布兼容性。
        </p>
      ) : (
        <div className="diagnosticList">
          {diagnostics.map((item, index) => (
            <div className={`diagnostic ${item.level}`} key={`${item.message}-${index}`}>
              <b>{item.level === "error" ? "错误" : item.level === "warning" ? "提醒" : "信息"}</b>
              <span>{item.message}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
