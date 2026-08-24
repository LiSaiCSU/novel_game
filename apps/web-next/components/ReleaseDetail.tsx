"use client";

import {
  ArrowRight,
  BookHeart,
  GitBranch,
  ListChecks,
  Map,
  ShieldCheck,
  Users,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { type CSSProperties, type FormEvent, useEffect, useRef, useState } from "react";
import { ErrorState, LoadingState, RetryButton } from "@/components/ui/async-state";
import { api, ApiError } from "@/lib/api";

type PlayerField = {
  key: string;
  label: string;
  type: "text" | "integer" | "choice" | "tags";
  required: boolean;
  default?: string | number | string[];
  minimum?: number;
  maximum?: number;
  choices: Array<{ value: string; label: string }>;
};

type Release = {
  id: string;
  title: string;
  summary: string;
  premise: string;
  rating: string;
  tags: string[];
  theme: { accent?: string };
  player_fields: PlayerField[];
  player_constraints: { gender?: string };
  content_counts: {
    locations: number;
    characters: number;
    plot_threads: number;
    quests: number;
  };
};

type Credential = { provider: string; model: string };

const defaultFields: PlayerField[] = [
  { key: "name", label: "姓名", type: "text", required: true, choices: [] },
  {
    key: "age",
    label: "年龄",
    type: "integer",
    required: true,
    default: 18,
    minimum: 18,
    maximum: 80,
    choices: [],
  },
];

const countLabels = [
  ["locations", "可探索地点", Map],
  ["characters", "重要人物", Users],
  ["plot_threads", "相互影响的剧情线", GitBranch],
  ["quests", "可推进任务", ListChecks],
] as const;

export function ReleaseDetail({ endpoint, shareToken }: { endpoint: string; shareToken?: string }) {
  const router = useRouter();
  const [work, setWork] = useState<Release>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [authenticated, setAuthenticated] = useState<boolean>();
  const [reloadKey, setReloadKey] = useState(0);
  const startIdempotencyKey = useRef("");

  useEffect(() => {
    api<Release>(endpoint)
      .then(setWork)
      .catch((exception) => setError((exception as Error).message));
    api<Credential[]>("/settings/llm-credentials")
      .then((items) => {
        setCredentials(items);
        setAuthenticated(true);
      })
      .catch((exception) => {
        if (exception instanceof ApiError && exception.status === 401) setAuthenticated(false);
      });
  }, [endpoint, reloadKey]);

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!work) return;
    if (authenticated === false) {
      const next = `${window.location.pathname}${window.location.search}`;
      router.push(`/?next=${encodeURIComponent(next)}`);
      return;
    }
    setBusy(true);
    setError("");
    const idempotencyKey = startIdempotencyKey.current || crypto.randomUUID();
    startIdempotencyKey.current = idempotencyKey;
    const data = new FormData(event.currentTarget);
    const playerConfig: Record<string, unknown> = {};
    const modelMode = String(data.get("model_mode") ?? "platform");
    playerConfig.model_mode = modelMode;
    if (modelMode.startsWith("byok:")) {
      playerConfig.model_mode = "byok";
      playerConfig.provider = modelMode.slice(5);
    }
    for (const field of work.player_fields) {
      if (["name", "age", "background"].includes(field.key)) continue;
      const raw = String(data.get(field.key) ?? "");
      playerConfig[field.key] =
        field.type === "tags"
          ? raw
              .split(/[，,]/)
              .map((item) => item.trim())
              .filter(Boolean)
          : raw;
    }
    try {
      const play = await api<{ id: string }>("/playthroughs", {
        method: "POST",
        body: JSON.stringify({
          release_id: work.id,
          share_token: shareToken,
          name: String(data.get("name") ?? "旅行者"),
          age: Number(data.get("age") || 18),
          gender: work.player_constraints.gender ?? "unspecified",
          background: String(data.get("background") ?? ""),
          player_config: playerConfig,
          // A paid platform opening is an LLM request just like a later turn.
          // Retrying this form after a lost response reuses the same durable
          // operation instead of creating and charging for a second world.
          idempotency_key: idempotencyKey,
        }),
      });
      startIdempotencyKey.current = "";
      router.push(`/play/${play.id}`);
    } catch (exception) {
      if (exception instanceof ApiError && exception.status === 401) {
        const next = `${window.location.pathname}${window.location.search}`;
        router.push(`/?next=${encodeURIComponent(next)}`);
        return;
      }
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !work) {
    return (
      <div className="routeState">
        <ErrorState
          title="作品没有顺利打开"
          description={error}
          action={
            <RetryButton
              onClick={() => {
                setError("");
                setWork(undefined);
                setReloadKey((value) => value + 1);
              }}
            />
          }
        />
      </div>
    );
  }
  if (!work) {
    return (
      <div className="routeState">
        <LoadingState label="正在打开作品与角色设定" />
      </div>
    );
  }

  const theme = { "--work-accent": work.theme.accent ?? "var(--rose)" } as CSSProperties;
  const fields = work.player_fields.length ? work.player_fields : defaultFields;

  return (
    <div className="page workDetail" style={theme}>
      <section className="workHero">
        <div className="workMonogram" aria-hidden="true">
          {work.title.slice(0, 1)}
        </div>
        <div className="workHeroCopy">
          <p className="eyebrow">
            {shareToken ? "受邀作品" : "已审核互动叙事"} · {work.rating}
          </p>
          <h1>{work.title}</h1>
          <p>{work.summary}</p>
          <div className="chips">
            {work.tags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
        </div>
      </section>

      <div className="workDetailGrid">
        <div className="workOverview">
          <section className="panel storyPremise">
            <p className="eyebrow">故事前提</p>
            <h2>进入这个世界之前</h2>
            <p className="premise">{work.premise || work.summary}</p>
          </section>
          <section className="workStats" aria-label="作品内容规模">
            {countLabels.map(([key, label, Icon]) => (
              <article key={key}>
                <Icon size={18} aria-hidden="true" />
                <b>{work.content_counts[key]}</b>
                <span>{label}</span>
              </article>
            ))}
          </section>
          <section className="readerPromise">
            <ShieldCheck aria-hidden="true" />
            <div>
              <b>你的选择属于这一局故事</b>
              <p>作品版本固定、关系边界明确，角色只依据自己知道的事实行动。</p>
            </div>
          </section>
        </div>

        <form className="panel stack characterForm" onSubmit={start}>
          <header>
            <span className="formStep">01 · 进入世界前</span>
            <BookHeart aria-hidden="true" />
            <p className="eyebrow">创建角色</p>
            <h2>让故事认识你</h2>
            <p>这些设定会成为叙事中的真实背景，你仍然可以在游戏里自由行动。</p>
          </header>
          {fields.map((field) => (
            <PlayerInput field={field} key={field.key} />
          ))}
          <label className="field">
            <span>叙事模型</span>
            <select className="select" name="model_mode">
              <option value="platform">平台额度（推荐）</option>
              {credentials.map((item) => (
                <option value={`byok:${item.provider}`} key={item.provider}>
                  我的 {item.provider === "compatible" ? "兼容模型" : item.provider} · {item.model}
                </option>
              ))}
            </select>
            <small>可在账户设置中添加只属于你的模型密钥。</small>
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="button primary startStoryButton" disabled={busy}>
            {busy ? "世界正在展开…" : authenticated === false ? "登录后开始故事" : "开始故事"}
            {!busy && <ArrowRight size={17} />}
          </button>
        </form>
      </div>
    </div>
  );
}

function PlayerInput({ field }: { field: PlayerField }) {
  const common = { id: field.key, name: field.key, required: field.required };
  if (field.type === "choice") {
    return (
      <label className="field">
        <span>{field.label}</span>
        <select
          className="select"
          {...common}
          defaultValue={String(field.default ?? field.choices[0]?.value ?? "")}
        >
          {field.choices.map((choice) => (
            <option value={choice.value} key={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (field.type === "integer") {
    return (
      <label className="field">
        <span>{field.label}</span>
        <input
          className="input"
          type="number"
          {...common}
          min={field.minimum}
          max={field.maximum}
          defaultValue={Number(field.default ?? field.minimum ?? 18)}
        />
      </label>
    );
  }
  if (field.key === "background") {
    return (
      <label className="field">
        <span>{field.label}</span>
        <textarea className="textarea" {...common} defaultValue={String(field.default ?? "")} />
      </label>
    );
  }
  return (
    <label className="field">
      <span>{field.label}</span>
      <input
        className="input"
        {...common}
        defaultValue={
          Array.isArray(field.default) ? field.default.join("，") : String(field.default ?? "")
        }
        placeholder={field.type === "tags" ? "用逗号分隔多个选项" : ""}
      />
    </label>
  );
}
