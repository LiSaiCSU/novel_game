"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { interfaceLabel } from "@/lib/display";

type AuditRow = {
  id: string;
  actor_id: string | null;
  actor_email: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  request_id: string;
  details: Record<string, unknown>;
  created_at: string;
};
type AuditFeed = { items: AuditRow[]; next_before: string | null; limit: number };
type AuditSummary = { hours: number; actions: Array<{ action: string; count: number }> };

/** Searchable operations trail. It presents metadata first, with detail on demand. */
export default function AuditTrailPanel() {
  const [feed, setFeed] = useState<AuditFeed>();
  const [summary, setSummary] = useState<AuditSummary>();
  const [prefix, setPrefix] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function readFeed(actionPrefix = "", before = "") {
    const params = new URLSearchParams({ limit: "30" });
    if (actionPrefix.trim()) params.set("action_prefix", actionPrefix.trim());
    if (before) params.set("before", before);
    return api<AuditFeed>(`/admin/audit-logs?${params.toString()}`);
  }

  useEffect(() => {
    Promise.all([readFeed(), api<AuditSummary>("/admin/audit-summary?hours=24")])
      .then(([initialFeed, initialSummary]) => {
        setFeed(initialFeed);
        setSummary(initialSummary);
        setError("");
      })
      .catch((exception: Error) => setError(exception.message));
  }, []);

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      setFeed(await readFeed(prefix));
      setError("");
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function loadMore() {
    if (!feed?.next_before) return;
    setBusy(true);
    try {
      const next = await readFeed(prefix, feed.next_before);
      setFeed({ ...next, items: [...feed.items, ...next.items] });
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel stack auditTrailPanel" id="audit-operations">
      <div className="entityToolbar">
        <div>
          <p className="eyebrow">可追溯运营</p>
          <h2>管理员操作审计</h2>
          <p>变更按请求 ID、操作者、目标和理由留档；默认不展示玩家故事正文。</p>
        </div>
        <span className="healthScore">近 {summary?.hours ?? 24} 小时</span>
      </div>
      {summary?.actions.length ? (
        <div className="auditSummary">
          {summary.actions.slice(0, 6).map((item) => (
            <span key={item.action} title={item.action}>
              <b>{item.count}</b>
              {interfaceLabel(item.action, item.action)}
            </span>
          ))}
        </div>
      ) : null}
      <form className="auditSearch" onSubmit={(event) => void search(event)}>
        <input
          className="input"
          value={prefix}
          maxLength={80}
          placeholder="按动作前缀筛选，例如 wallet. 或 user."
          onChange={(event) => setPrefix(event.target.value)}
        />
        <button className="button" disabled={busy}>
          {busy ? "查询中…" : "筛选记录"}
        </button>
      </form>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="auditRows">
        {feed?.items.map((row) => (
          <article key={row.id}>
            <div className="auditRowHead">
              <div>
                <b>{interfaceLabel(row.action, row.action)}</b>
                <span>{row.action}</span>
              </div>
              <time dateTime={row.created_at}>
                {new Date(row.created_at).toLocaleString("zh-CN")}
              </time>
            </div>
            <small>
              操作者：{row.actor_email || row.actor_id || "系统"} · 目标：{row.target_type}
              {row.target_id ? `/${row.target_id.slice(0, 12)}` : ""} · 请求 {row.request_id || "—"}
            </small>
            {Object.keys(row.details).length > 0 && (
              <details>
                <summary>查看审计详情</summary>
                <pre>{JSON.stringify(row.details, null, 2)}</pre>
              </details>
            )}
          </article>
        ))}
        {!feed?.items.length && !error && <p className="emptyState">当前筛选条件下没有记录。</p>}
      </div>
      {feed?.next_before && (
        <button type="button" className="button" disabled={busy} onClick={() => void loadMore()}>
          加载更早记录
        </button>
      )}
    </section>
  );
}
