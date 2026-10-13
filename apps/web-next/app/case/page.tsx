"use client";

import { ArrowRight, Clock3, Fingerprint, Gavel, Search, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CardSkeletons, ErrorState, RetryButton } from "@/components/ui/async-state";
import { api } from "@/lib/api";
import "./case.css";

type CaseSummary = {
  key: string;
  title: string;
  tagline: string;
  setting: string;
  estimated_minutes: string;
  minutes_total: number;
  suspects: number;
};

type RunSummary = {
  id: string;
  case_key: string;
  title: string;
  status: "briefing" | "active" | "deadline" | "closed";
  ending_title: string | null;
  solved: boolean;
  minutes_left: number | null;
  updated_at: string | null;
};

const statusLabel: Record<RunSummary["status"], string> = {
  briefing: "还没开始",
  active: "调查中",
  deadline: "等待指认",
  closed: "已结案",
};

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
    if (!window.confirm(`删除这份「${run.title}」案卷？`)) return;
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
          <Fingerprint size={15} aria-hidden="true" /> 推理对决
        </p>
        <h1>每个人都在说谎。你只有一次指认的机会。</h1>
        <p>
          勘查现场、问话、拿证据戳穿谎言，在时间耗尽之前说出凶手、凶器和动机。
          大部分时候你只需要做选择；想自己发问，AI 会扮演对方回答你。
        </p>
        <ul className="caseLobbyRules">
          <li>
            <Search size={16} aria-hidden="true" /> 找证据
          </li>
          <li>
            <Users size={16} aria-hidden="true" /> 戳穿说法
          </li>
          <li>
            <Clock3 size={16} aria-hidden="true" /> 跟时间赛跑
          </li>
          <li>
            <Gavel size={16} aria-hidden="true" /> 一次指认
          </li>
        </ul>
      </header>

      {error && <p className="error">{error}</p>}

      <section aria-labelledby="cases-title">
        <h2 id="cases-title" className="caseLobbyHead">
          案件
        </h2>
        {loading && <CardSkeletons count={1} />}
        {!loading && !cases.length && !error && (
          <ErrorState
            title="还没有可以调查的案子"
            description="案件列表是空的。"
            action={<RetryButton onClick={() => setReloadKey((key) => key + 1)} />}
          />
        )}
        <div className="caseLobbyGrid">
          {cases.map((item) => (
            <article className="caseLobbyCard" key={item.key}>
              <p className="eyebrow">{item.setting}</p>
              <h3>{item.title}</h3>
              <p>{item.tagline}</p>
              <p className="caseHint">
                {item.suspects} 名嫌疑人 · 游戏内 {item.minutes_total} 分钟 · 约{" "}
                {item.estimated_minutes}
              </p>
              <button
                className="button primary"
                onClick={() => void start(item.key)}
                disabled={starting === item.key}
              >
                {starting === item.key ? "正在打开案卷……" : "接手这件案子"} <ArrowRight size={16} />
              </button>
            </article>
          ))}
        </div>
      </section>

      {signedIn && runs.length > 0 && (
        <section aria-labelledby="runs-title">
          <h2 id="runs-title" className="caseLobbyHead">
            我的案卷
          </h2>
          <ul className="caseRunList">
            {runs.map((run) => (
              <li key={run.id}>
                <Link href={`/case/${run.id}`}>
                  <b>{run.title}</b>
                  <span>
                    {run.status === "closed"
                      ? `${run.solved ? "✓ " : ""}${run.ending_title ?? "已结案"}`
                      : `${statusLabel[run.status]}${
                          run.status === "active" && run.minutes_left !== null
                            ? ` · 剩 ${run.minutes_left} 分钟`
                            : ""
                        }`}
                  </span>
                </Link>
                <button
                  className="caseIconButton"
                  onClick={() => void remove(run)}
                  aria-label="删除案卷"
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
