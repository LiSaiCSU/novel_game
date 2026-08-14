"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Preview = {
  title: string;
  summary: string;
  rating: string;
  locale: string;
  revision: number;
  diagnostics: Array<{ level: string; message: string }>;
  content_counts: Record<string, number>;
};

export default function SharedPreview() {
  const { token } = useParams<{ token: string }>();
  const [preview, setPreview] = useState<Preview>();
  const [error, setError] = useState("");
  useEffect(() => {
    api<Preview>(`/creator/shared/${token}`)
      .then(setPreview)
      .catch((exception) => setError(exception.message));
  }, [token]);
  if (error)
    return (
      <div className="page">
        <div className="error">{error}</div>
      </div>
    );
  if (!preview) return <div className="page">正在打开只读草稿…</div>;
  return (
    <div className="page">
      <div className="pageHead">
        <div>
          <p className="eyebrow">只读创作预览 · REVISION {preview.revision}</p>
          <h1>{preview.title}</h1>
          <p>{preview.summary}</p>
        </div>
        <Link className="button" href="/library">
          浏览已发布作品
        </Link>
      </div>
      <section className="panel">
        <div className="meta">
          <span>{preview.locale}</span>
          <span>{preview.rating}</span>
        </div>
        <div className="workStats">
          {Object.entries(preview.content_counts).map(([key, value]) => (
            <article key={key}>
              <b>{value}</b>
              <span>{key}</span>
            </article>
          ))}
        </div>
      </section>
      <section className="panel spacedPanel">
        <h2>发布前诊断</h2>
        {preview.diagnostics.length === 0 ? (
          <p className="success">当前结构校验通过</p>
        ) : (
          preview.diagnostics.map((item, index) => (
            <div className="diagnostic" key={index}>
              <b>{item.level}</b>
              <span>{item.message}</span>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
