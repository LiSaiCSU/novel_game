"use client";

import {
  ArrowRight,
  BookOpen,
  ChevronDown,
  FileArchive,
  FileText,
  Plus,
  Sparkles,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { interfaceLabel } from "@/lib/display";
import { CardSkeletons, EmptyState, ErrorState, RetryButton } from "@/components/ui/async-state";

type Project = {
  id: string;
  slug: string;
  title: string;
  summary: string;
  status: string;
  revision: number;
  updated_at: string;
};

type Credential = { provider: string; model: string; status: string };

function newImportKey() {
  return typeof globalThis.crypto?.randomUUID === "function"
    ? globalThis.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function Creator() {
  const router = useRouter();
  const importKey = useRef("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [error, setError] = useState("");
  const [importingStory, setImportingStory] = useState(false);
  const [importingPack, setImportingPack] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [modelMode, setModelMode] = useState<"platform" | "byok">("platform");

  useEffect(() => {
    Promise.all([
      api<Project[]>("/creator/projects"),
      api<Credential[]>("/settings/llm-credentials"),
    ])
      .then(([items, keys]) => {
        setProjects(items);
        setCredentials(keys.filter((item) => item.status === "active"));
        setError("");
      })
      .catch((exception) => setError((exception as Error).message))
      .finally(() => setLoading(false));
  }, [reloadKey]);

  async function importStory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setImportingStory(true);
    setError("");
    const form = new FormData(event.currentTarget);
    if (!importKey.current) importKey.current = newImportKey();
    form.set("idempotency_key", importKey.current);
    try {
      const project = await api<Project>("/creator/import-story", { method: "POST", body: form });
      importKey.current = "";
      router.push(`/creator/${project.id}?from=text`);
    } catch (exception) {
      // A response confirms the request did not create a draft; the next
      // deliberate click gets a fresh attempt. Keep the key on a network
      // failure so a lost success response can still be recovered safely.
      if (exception instanceof ApiError) importKey.current = "";
      setError((exception as Error).message);
      setImportingStory(false);
    }
  }

  async function importPack(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setImportingPack(true);
    setError("");
    try {
      const project = await api<Project>("/creator/import", {
        method: "POST",
        body: new FormData(event.currentTarget),
      });
      router.push(`/creator/${project.id}`);
    } catch (exception) {
      setError((exception as Error).message);
      setImportingPack(false);
    }
  }

  return (
    <div className="page creatorHome">
      <div className="pageHead">
        <div>
          <p className="eyebrow">创作工作台</p>
          <h1>把故事变成可玩的世界</h1>
          <p>
            不需要懂 JSON 或游戏脚本。先写下想法，或上传你的 TXT
            小说/大纲，我们会准备一份可继续修改的互动剧情初稿。
          </p>
        </div>
        <Link className="button primary" href="/creator/new">
          <Plus size={17} /> 从想法开始
        </Link>
      </div>

      <section className="creatorSteps" aria-label="创作方式">
        <article>
          <span className="creatorStepIcon">
            <BookOpen size={20} />
          </span>
          <b>1. 写一个想法</b>
          <p>用标题和一句冲突，马上得到可编辑的故事骨架。</p>
          <Link href="/creator/new">
            新建故事 <ArrowRight size={14} />
          </Link>
        </article>
        <article className="featured">
          <span className="creatorStepIcon">
            <Sparkles size={20} />
          </span>
          <b>2. 用 TXT 做成互动剧情</b>
          <p>上传自己写的小说、章节或整理好的设定，让 AI 提炼场景、人物与开场冲突。</p>
          <a href="#text-import">
            开始导入 <ArrowRight size={14} />
          </a>
        </article>
        <article>
          <span className="creatorStepIcon">
            <Upload size={20} />
          </span>
          <b>3. 补封面并试玩</b>
          <p>在编辑页上传封面、调整初稿，随时预览玩家看到的体验。</p>
          <span>每一步都可以回头修改</span>
        </article>
      </section>

      <section className="guidedImport" id="text-import" aria-labelledby="text-import-heading">
        <div className="guidedImportCopy">
          <span className="eyebrow">
            <FileText size={14} /> TXT 智能导入
          </span>
          <h2 id="text-import-heading">把已有文字变成新的剧情起点</h2>
          <p>
            支持 UTF-8、UTF-16、GB18030 编码的 .txt 文件，最大 1 MB / 18,000
            字符。较长小说请按章节导入或先整理成大纲。AI
            只在这次生成中阅读原文；平台保存的是生成后的草稿，不会把你的原文作为文档留存。
          </p>
        </div>
        <form className="guidedImportForm" onSubmit={importStory}>
          <label className="field">
            <span>TXT 小说、章节或大纲</span>
            <input className="input" name="file" type="file" accept=".txt,text/plain" required />
          </label>
          <label className="field">
            <span>作品标题（可选）</span>
            <input
              className="input"
              name="title"
              maxLength={120}
              placeholder="让 AI 从原文取标题"
            />
          </label>
          <div className="guidedImportOptions">
            <label className="field">
              <span>生成方式</span>
              <select
                className="select"
                name="model_mode"
                value={modelMode}
                onChange={(event) => setModelMode(event.target.value as "platform" | "byok")}
              >
                <option value="platform">使用平台 AI</option>
                <option value="byok" disabled={!credentials.length}>
                  使用我的 AI 密钥
                </option>
              </select>
            </label>
            {modelMode === "byok" && (
              <label className="field">
                <span>已保存的模型</span>
                <select className="select" name="provider" required>
                  {credentials.map((item) => (
                    <option value={item.provider} key={item.provider}>
                      {item.provider} · {item.model}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="field">
              <span>内容分级</span>
              <select className="select" name="rating" defaultValue="16+">
                <option value="all">全年龄</option>
                <option value="13+">13+</option>
                <option value="16+">16+</option>
                <option value="18+">18+</option>
              </select>
            </label>
          </div>
          {modelMode === "byok" && !credentials.length && (
            <p className="studioHint">请先在账户设置中保存并测试一个 AI 密钥，或者改用平台 AI。</p>
          )}
          {modelMode === "byok" && credentials.length > 0 && (
            <p className="studioHint">
              原文会发送给你在上方选择的模型提供商处理，并适用该提供商的数据条款。
            </p>
          )}
          <button
            className="button primary"
            disabled={importingStory || (modelMode === "byok" && !credentials.length)}
          >
            <Sparkles size={16} /> {importingStory ? "正在理解并搭建初稿…" : "生成可编辑剧情初稿"}
          </button>
        </form>
      </section>

      <details className="advancedImport">
        <summary>
          <FileArchive size={16} /> 已有专业内容文件？
          <span>
            高级导入 <ChevronDown size={15} />
          </span>
        </summary>
        <form className="advancedImportForm" onSubmit={importPack}>
          <p>
            这里仅供使用过专业导出工具的创作者导入 JSON、YAML 或 ZIP 内容包；普通创作不需要这一步。
          </p>
          <input
            className="input"
            type="file"
            name="file"
            accept=".json,.yaml,.yml,.zip"
            required
          />
          <button className="button" disabled={importingPack}>
            {importingPack ? "正在检查…" : "导入专业文件"}
          </button>
        </form>
      </details>

      {error ? (
        <ErrorState
          title="创作工作台暂时无法完成操作"
          description={error}
          action={
            <RetryButton
              onClick={() => {
                setLoading(true);
                setError("");
                setReloadKey((value) => value + 1);
              }}
            />
          }
        />
      ) : loading ? (
        <CardSkeletons count={3} />
      ) : projects.length === 0 ? (
        <EmptyState
          title="从第一段故事开始"
          description="选择“从想法开始”，或把已有 TXT 导入为可编辑的互动故事草稿。"
          action={
            <Link className="button primary" href="/creator/new">
              开始创作 <ArrowRight size={16} />
            </Link>
          }
        />
      ) : (
        <section aria-labelledby="my-projects-heading">
          <div className="sectionHead">
            <h2 id="my-projects-heading">我的故事</h2>
            <span>{projects.length} 个项目</span>
          </div>
          <div className="cardGrid">
            {projects.map((project) => (
              <Link className="workCard" href={`/creator/${project.id}`} key={project.id}>
                <div className="workBody">
                  <div className="meta">
                    <span className={`projectStatus ${project.status}`}>
                      {interfaceLabel(project.status, "状态已更新")}
                    </span>
                    <span>修订 {project.revision}</span>
                  </div>
                  <h2>{project.title}</h2>
                  <p className="studioHint">{project.summary || "还没有填写简介"}</p>
                  <small>上次编辑：{new Date(project.updated_at).toLocaleString("zh-CN")}</small>
                  <span className="cardLink">
                    继续创作 <ArrowRight size={15} />
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
