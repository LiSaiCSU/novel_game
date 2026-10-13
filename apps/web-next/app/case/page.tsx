"use client";

import { ArrowRight, Clock3, Fingerprint, Route, Shuffle, Star, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { CardSkeletons, ErrorState, RetryButton } from "@/components/ui/async-state";
import { api } from "@/lib/api";
import "./case.css";

type CaseSummary = {
  key: string;
  mode: "deduction" | "scheme";
  title: string;
  tagline: string;
  setting: string;
  estimated_minutes: string;
  minutes_total: number;
  suspects: number;
  routes_total: number;
};

type RunSummary = {
  id: string;
  case_key: string;
  title: string;
  status: "briefing" | "active" | "deadline" | "closed";
  ending_title: string | null;
  solved: boolean;
  route: string | null;
  grade: string | null;
  minutes_left: number | null;
  updated_at: string | null;
};

const statusLabel: Record<RunSummary["status"], string> = {
  briefing: "还没开始",
  active: "进行中",
  deadline: "等待指认",
  closed: "已结束",
};

const modeLabel: Record<CaseSummary["mode"], string> = {
  scheme: "十分钟博弈",
  deduction: "推理对决",
};

function runLine(run: RunSummary): string {
  if (run.status !== "closed") {
    const left =
      run.status === "active" && run.minutes_left !== null ? ` · 剩 ${run.minutes_left} 分钟` : "";
    return `${statusLabel[run.status]}${left}`;
  }
  const grade = run.grade ? `${run.grade} · ` : run.solved ? "✓ " : "";
  return `${grade}${run.ending_title ?? "已结束"}`;
}

export default function CaseLobby() {
  const router = useRouter();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [signedIn, setSignedIn] = useState(true);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState("");
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    api<CaseSummary[]>("/cases")
      .then(setCases)
      .catch((exception) => setError((exception as Error).message))
      .finally(() => setLoading(false));
    api<RunSummary[]>("/case-runs")
      .then((items) => {
        setRuns(items);
        setSignedIn(true);
      })
      .catch(() => setSignedIn(false));
  }, [reloadKey]);

  // Short schemes first: they are the quickest way in.
  const ordered = useMemo(
    () => [...cases].sort((a, b) => Number(a.mode !== "scheme") - Number(b.mode !== "scheme")),
    [cases],
  );

  const found = useMemo(() => {
    const byCase: Record<string, Set<string>> = {};
    for (const run of runs) {
      if (run.solved && run.route) (byCase[run.case_key] ??= new Set()).add(run.route);
    }
    return byCase;
  }, [runs]);

  async function start(key: string) {
    if (!signedIn) {
      router.push("/login?next=/case");
      return;
    }
    setStarting(key);
    setError("");
    try {
      const run = await api<{ id: string }>("/case-runs", {
        method: "POST",
        body: JSON.stringify({ case_key: key }),
      });
      router.push(`/case/${run.id}`);
    } catch (exception) {
      setError((exception as Error).message);
      setStarting("");
    }
  }

  async function remove(run: RunSummary) {
    if (!window.confirm(`删除这份「${run.title}」记录？`)) return;
    try {
      await api(`/case-runs/${run.id}`, { method: "DELETE" });
      setRuns((current) => current.filter((item) => item.id !== run.id));
    } catch (exception) {
      setError((exception as Error).message);
    }
  }

  return (
    <div className="page caseLobby">
      <header className="caseLobbyHero">
        <p className="eyebrow">
          <Fingerprint size={15} aria-hidden="true" /> 十分钟一局
        </p>
        <h1>一个目标，五种赢法。你只有这一次机会。</h1>
        <p>
          每一局开场就告诉你要做成什么、还剩几分钟。揭穿、交易、借刀、诈，甚至转身就走——
          怎么赢由你选，赢得漂不漂亮另算。每一局证据藏的地方都会变，这一次没走通的路，下一次也许就在眼前。
        </p>
        <ul className="caseLobbyRules">
          <li>
            <Clock3 size={16} aria-hidden="true" /> 8—12 分钟一局
          </li>
          <li>
            <Route size={16} aria-hidden="true" /> 多条路线
          </li>
          <li>
            <Shuffle size={16} aria-hidden="true" /> 每局不同
          </li>
          <li>
            <Star size={16} aria-hidden="true" /> 三星评级
          </li>
        </ul>
      </header>

      {error && <p className="error">{error}</p>}

      <section aria-labelledby="cases-title">
        <h2 id="cases-title" className="caseLobbyHead">
          剧本
        </h2>
        {loading && <CardSkeletons count={1} />}
        {!loading && !cases.length && !error && (
          <ErrorState
            title="还没有可以玩的剧本"
            description="剧本列表是空的。"
            action={<RetryButton onClick={() => setReloadKey((key) => key + 1)} />}
          />
        )}
        <div className="caseLobbyGrid">
          {ordered.map((item) => (
            <article className={`caseLobbyCard mode-${item.mode}`} key={item.key}>
              <p className="eyebrow">
                <span className="caseModeTag">{modeLabel[item.mode]}</span> {item.setting}
              </p>
              <h3>{item.title}</h3>
              <p>{item.tagline}</p>
              <p className="caseHint">
                {item.mode === "scheme"
                  ? `已找到解法 ${found[item.key]?.size ?? 0}/${item.routes_total} · 约 ${item.estimated_minutes}`
                  : `${item.suspects} 名嫌疑人 · 游戏内 ${item.minutes_total} 分钟 · 约 ${item.estimated_minutes}`}
              </p>
              <button
                className="button primary"
                onClick={() => void start(item.key)}
                disabled={starting === item.key}
              >
                {starting === item.key
                  ? "正在开场……"
                  : item.mode === "scheme"
                    ? "开局"
                    : "接手这件案子"}{" "}
                <ArrowRight size={16} />
              </button>
            </article>
          ))}
        </div>
      </section>

      {signedIn && runs.length > 0 && (
        <section aria-labelledby="runs-title">
          <h2 id="runs-title" className="caseLobbyHead">
            我的记录
          </h2>
          <ul className="caseRunList">
            {runs.map((run) => (
              <li key={run.id}>
                <Link href={`/case/${run.id}`}>
                  <b>{run.title}</b>
                  <span>{runLine(run)}</span>
                </Link>
                <button
                  className="caseIconButton"
                  onClick={() => void remove(run)}
                  aria-label="删除记录"
                >
                  <Trash2 size={16} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
