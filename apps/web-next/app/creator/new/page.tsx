"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

type ProjectTemplate = {
  key: string;
  title: string;
  description: string;
  genre_tags: string[];
  recommended_for: string;
  complexity: "starter" | "guided" | "advanced";
  counts: {
    locations: number;
    characters: number;
    facts: number;
    quests: number;
    plot_threads: number;
  };
};

const complexityLabel = { starter: "最小起步", guided: "带示例", advanced: "进阶" };

export default function NewProject() {
  const router = useRouter();
  const [templates, setTemplates] = useState<ProjectTemplate[]>([]);
  const [templateKey, setTemplateKey] = useState("relationship_drama");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<ProjectTemplate[]>("/creator/templates")
      .then(setTemplates)
      .catch((exception) => setError((exception as Error).message));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const project = await api<{ id: string }>("/creator/projects", {
        method: "POST",
        body: JSON.stringify({
          title: data.get("title"),
          slug: data.get("slug"),
          summary: data.get("summary"),
          rating: data.get("rating"),
          locale: "zh-CN",
          template_key: templateKey,
        }),
      });
      router.push(`/creator/${project.id}`);
    } catch (exception) {
      setError((exception as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="page newProjectPage">
      <div className="pageHead">
        <div>
          <p className="eyebrow">创建新作品</p>
          <h1>从一个可玩的骨架开始。</h1>
          <p>模板只负责提供正确的结构和示例，不会替你决定世界观。创建后每个字段都可以修改。</p>
        </div>
      </div>

      <form className="newProjectLayout" onSubmit={submit}>
        <section className="panel stack">
          <h2>作品信息</h2>
          <label className="field" htmlFor="title">
            <span>作品标题</span>
            <input className="input" id="title" name="title" required />
          </label>
          <label className="field" htmlFor="slug">
            <span>网址标识</span>
            <input
              className="input"
              id="slug"
              name="slug"
              pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
              placeholder="my-story"
              required
            />
          </label>
          <label className="field" htmlFor="summary">
            <span>一句话冲突</span>
            <textarea
              className="textarea"
              id="summary"
              name="summary"
              placeholder="谁想要什么，为什么现在必须行动？"
            />
          </label>
          <label className="field" htmlFor="rating">
            <span>内容分级</span>
            <select className="select" id="rating" name="rating" defaultValue="16+">
              <option>all</option>
              <option>13+</option>
              <option>16+</option>
            </select>
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="button primary" disabled={busy || templates.length === 0}>
            {busy ? "正在建立…" : "创建并进入创作台"}
          </button>
        </section>

        <fieldset className="templatePicker">
          <legend>选择创作骨架</legend>
          {templates.length === 0 && !error && <div className="empty">正在检查可用模板…</div>}
          {templates.map((template) => (
            <label
              className={`templateCard ${templateKey === template.key ? "selected" : ""}`}
              key={template.key}
            >
              <input
                type="radio"
                name="template"
                value={template.key}
                checked={templateKey === template.key}
                onChange={() => setTemplateKey(template.key)}
              />
              <span className="templateBadge">{complexityLabel[template.complexity]}</span>
              <strong>{template.title}</strong>
              <p>{template.description}</p>
              <small>适合：{template.recommended_for}</small>
              <div className="chips">
                {template.genre_tags.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
              <dl className="templateCounts">
                <div>
                  <dt>地点</dt>
                  <dd>{template.counts.locations}</dd>
                </div>
                <div>
                  <dt>人物</dt>
                  <dd>{template.counts.characters}</dd>
                </div>
                <div>
                  <dt>事实</dt>
                  <dd>{template.counts.facts}</dd>
                </div>
                <div>
                  <dt>任务</dt>
                  <dd>{template.counts.quests}</dd>
                </div>
                <div>
                  <dt>线程</dt>
                  <dd>{template.counts.plot_threads}</dd>
                </div>
              </dl>
            </label>
          ))}
        </fieldset>
      </form>
    </div>
  );
}
