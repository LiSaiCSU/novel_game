"use client";

import { ArrowRight, FileArchive, Plus } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
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

export default function Creator() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState("");
  const [importing, setImporting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    api<Project[]>("/creator/projects")
      .then((items) => {
        setProjects(items);
        setError("");
      })
      .catch((exception) => setError(exception.message))
      .finally(() => setLoading(false));
  }, [reloadKey]);

  async function importPack(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setImporting(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const project = await api<Project>("/creator/import", { method: "POST", body: form });
      router.push(`/creator/${project.id}`);
    } catch (exception) {
      setError((exception as Error).message);
      setImporting(false);
    }
  }

  return (
    <div className="page">
      <div className="pageHead">
        <div>
          <p className="eyebrow">创作工作台</p>
          <h1>创作台</h1>
          <p>结构化编辑世界、人物与规则，实时校验引用，预览后生成不可变版本。</p>
        </div>
        <Link className="button primary" href="/creator/new">
          <Plus size={17} />
          创建新作品
        </Link>
      </div>
      <form className="importPanel" onSubmit={importPack}>
        <FileArchive aria-hidden="true" />
        <div className="importCopy">
          <b>已有 Content Pack？</b>
          <p>导入 UTF-8 JSON、YAML 或安全 ZIP；不会执行包内代码。</p>
        </div>
        <input className="input" type="file" name="file" accept=".json,.yaml,.yml,.zip" required />
        <button className="button" disabled={importing}>
          {importing ? "正在校验…" : "导入"}
        </button>
      </form>
      {error ? (
        <ErrorState
          title="创作项目没有加载成功"
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
          title="从第一份世界设定开始"
          description="创建向导会准备一份可以立即预览的 v2 内容包，你可以从空白项目或官方结构模板开始。"
          action={
            <Link className="button primary" href="/creator/new">
              创建作品 <ArrowRight size={16} />
            </Link>
          }
        />
      ) : (
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
                <p className="studioHint">{project.summary || "尚未填写简介"}</p>
                <small>最后编辑 {new Date(project.updated_at).toLocaleString("zh-CN")}</small>
                <span className="cardLink">
                  继续编辑 <ArrowRight size={15} />
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
