"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, RefreshCw, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";

type Severity = "critical" | "warning" | "info";
type OperationsAlert = {
  code: string;
  severity: Severity;
  title: string;
  description: string;
  value: number;
  href: string;
};
type OperationsAlertFeed = {
  generated_at: string;
  window_hours: number;
  healthy: boolean;
  counts: { critical: number; warning: number };
  alerts: OperationsAlert[];
};

const severityLabel: Record<Severity, string> = {
  critical: "立即处理",
  warning: "需要关注",
  info: "运营提示",
};

/**
 * Current operational facts, rather than dismissible client notifications.
 * Each signal points to the panel where an MFA/audited action can be taken.
 */
export default function OperationsAlertsPanel() {
  const [feed, setFeed] = useState<OperationsAlertFeed>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setBusy(true);
    try {
      setFeed(await api<OperationsAlertFeed>("/admin/operations-alerts"));
      setError("");
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    api<OperationsAlertFeed>("/admin/operations-alerts")
      .then((result) => {
        setFeed(result);
        setError("");
      })
      .catch((exception: Error) => setError(exception.message));
  }, []);

  return (
    <section className="panel stack operationsAlertsPanel" id="operations-alerts">
      <div className="entityToolbar">
        <div>
          <p className="eyebrow">主动运营</p>
          <h2>
            <TriangleAlert size={19} aria-hidden="true" /> 风险信号
          </h2>
          <p>由账本、工单、模型用量和安全审计实时计算；不能通过“已读”掩盖未解决风险。</p>
        </div>
        <button className="button secondary" type="button" disabled={busy} onClick={() => void load()}>
          <RefreshCw size={16} aria-hidden="true" /> {busy ? "刷新中…" : "刷新信号"}
        </button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {feed?.alerts.length ? (
        <div className="operationsAlertRows">
          {feed.alerts.map((alert) => (
            <article className={alert.severity} key={alert.code}>
              <div>
                <span>{severityLabel[alert.severity]}</span>
                <b>{alert.title}</b>
                <p>{alert.description}</p>
              </div>
              <a className="button secondary" href={alert.href}>
                前往处理
              </a>
            </article>
          ))}
        </div>
      ) : feed?.healthy ? (
        <p className="emptyState healthyState">
          <CheckCircle2 size={18} aria-hidden="true" /> 当前没有触发的运营风险信号。
        </p>
      ) : null}
      {feed && (
        <p className="studioHint">
          最近 {feed.window_hours} 小时 · {feed.counts.critical} 项需立即处理 · {feed.counts.warning} 项需要关注 ·
          生成于 {new Date(feed.generated_at).toLocaleString("zh-CN")}
        </p>
      )}
    </section>
  );
}
