"use client";

import { ArrowRight, Sparkles } from "lucide-react";
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

const templateLabel = {
  blank: "从空白故事开始",
  relationship_drama: "角色关系故事",
  mystery: "悬疑与调查故事",
};

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
          summary: data.get("summary"),
          rating: data.get("rating"),
          locale: "zh-CN",
          template_key: templateKey,
        }),
      });
      router.push(`/creator/${project.id}?from=idea`);
    } catch (exception) {
      setError((exception as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="page newProjectPage">
      <div className="pageHead">
        <div>
          <p className="eyebrow">新建故事</p>
          <h1>先让读者想继续往下走</h1>
          <p>
            只需要一个标题和一句“现在为什么必须行动”。我们会在背后准备好游戏需要的基础结构，之后你可以在编辑器里慢慢丰富。
          </p>
        </div>
      </div>

      <form className="newProjectLayout" onSubmit={submit}>
        <section className="panel stack newStoryEssentials">
          <div>
            <span className="eyebrow">第一步</span>
            <h2>故事的种子</h2>
          </div>
          <label className="field" htmlFor="title">
            <span>作品标题</span>
            <input
              className="input"
              id="title"
              name="title"
              required
              maxLength={120}
              placeholder="例如：雨夜失物招领处"
              autoFocus
            />
          </label>
          <label className="field" htmlFor="summary">
            <span>一句话冲突</span>
            <textarea
              className="textarea"
              id="summary"
              name="summary"
              required
              maxLength={1000}
              placeholder="谁想要什么？为什么现在不行动就来不及？"
            />
          </label>
          <label className="field" htmlFor="rating">
            <span>内容分级</span>
            <select className="select" id="rating" name="rating" defaultValue="16+">
              <option value="all">全年龄</option>
              <option value="13+">13+</option>
              <option value="16+">16+</option>
              <option value="18+">18+</option>
            </select>
          </label>
          <p className="studioHint">
            项目地址会自动生成，不需要填写技术标识。创建后可上传封面、添加人物和场景，并立即试玩。
          </p>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="button primary" disabled={busy || templates.length === 0}>
            <Sparkles size={16} /> {busy ? "正在准备故事…" : "创建并进入故事工作台"}{" "}
            <ArrowRight size={16} />
          </button>
        </section>

        <fieldset className="templatePicker">
          <legend>第二步：选择一个适合的起点</legend>
          <p className="studioHint">这不是限制。它只是替你放好第一批场景和人物，所有内容都能改。</p>
          {templates.length === 0 && !error && <div className="empty">正在准备创作起点…</div>}
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
              <span className="templateBadge">
                {templateLabel[template.key as keyof typeof templateLabel] ?? "故事起点"}
              </span>
              <strong>{template.title}</strong>
              <p>{template.description}</p>
              <small>适合：{template.recommended_for}</small>
              <div className="chips">
                {template.genre_tags.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
              <dl className="templateCounts" aria-label="初始内容数量">
                <div>
                  <dt>地点</dt>
                  <dd>{template.counts.locations}</dd>
                </div>
                <div>
                  <dt>人物</dt>
                  <dd>{template.counts.characters}</dd>
                </div>
                <div>
                  <dt>线索</dt>
                  <dd>{template.counts.facts}</dd>
                </div>
                <div>
                  <dt>目标</dt>
                  <dd>{template.counts.quests}</dd>
                </div>
                <div>
                  <dt>剧情线</dt>
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
