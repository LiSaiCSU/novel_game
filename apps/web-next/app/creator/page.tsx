"use client";

import Link from "next/link";
import {FormEvent, useEffect, useState} from "react";
import {useRouter} from "next/navigation";
import {api} from "@/lib/api";

type Project = {id: string; slug: string; title: string; summary: string; status: string; revision: number; updated_at: string};

export default function Creator() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState("");
  const [importing, setImporting] = useState(false);
  useEffect(() => {api<Project[]>("/creator/projects").then(setProjects).catch(exception => setError(exception.message));}, []);

  async function importPack(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setImporting(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const project = await api<Project>("/creator/import", {method: "POST", body: form});
      router.push(`/creator/${project.id}`);
    } catch (exception) {
      setError((exception as Error).message);
      setImporting(false);
    }
  }

  return <main className="page">
    <div className="pageHead"><div><p className="eyebrow">CREATOR STUDIO</p><h1>创作台</h1><p>结构化编辑世界、人物与规则，实时校验引用，预览后生成不可变版本。</p></div><Link className="button primary" href="/creator/new">创建新作品</Link></div>
    {error && <p className="error">{error}</p>}
    <form className="importPanel" onSubmit={importPack}><div><b>已有 Content Pack？</b><p>导入 UTF-8 JSON、YAML 或安全 ZIP；不会执行包内代码。</p></div><input className="input" type="file" name="file" accept=".json,.yaml,.yml,.zip" required/><button className="button" disabled={importing}>{importing ? "正在校验…" : "导入"}</button></form>
    {projects.length === 0 ? <div className="empty"><h2>从第一份世界设定开始</h2><p>创建向导会准备一份可以立即预览的 v2 内容包。</p></div> : <div className="cardGrid">{projects.map(project => <Link className="workCard" href={`/creator/${project.id}`} key={project.id}><div className="workBody"><div className="meta"><span>{project.status}</span><span>修订 {project.revision}</span></div><h2>{project.title}</h2><p className="studioHint">{project.summary || "尚未填写简介"}</p><small>{new Date(project.updated_at).toLocaleString()}</small></div></Link>)}</div>}
  </main>;
}
