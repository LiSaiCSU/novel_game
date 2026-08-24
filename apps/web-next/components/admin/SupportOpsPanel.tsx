"use client";

import { FormEvent, useEffect, useState } from "react";
import { Headphones, Send } from "lucide-react";
import { api } from "@/lib/api";

type CaseStatus = "open" | "in_progress" | "waiting_user" | "resolved" | "closed";
type CasePriority = "low" | "normal" | "high" | "urgent";

type Operator = { id: string; email: string; display_name: string };
type SupportCase = {
  id: string;
  category: string;
  status: CaseStatus;
  priority: CasePriority;
  subject: string;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  player: { id: string; email: string; display_name: string };
};
type SupportMessage = {
  id: string;
  author_role: "player" | "admin";
  author_id: string | null;
  body: string;
  created_at: string;
};
type CaseDetail = SupportCase & {
  assigned_operator: Operator | null;
  messages: SupportMessage[];
};
type QueueSummary = {
  created_24h: number;
  unassigned_open: number;
  oldest_open_at: string | null;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
};

const statusLabels: Record<CaseStatus, string> = {
  open: "待受理",
  in_progress: "处理中",
  waiting_user: "等待玩家",
  resolved: "已解决",
  closed: "已关闭",
};
const priorityLabels: Record<CasePriority, string> = {
  low: "低",
  normal: "普通",
  high: "高",
  urgent: "紧急",
};

export default function SupportOpsPanel() {
  const [summary, setSummary] = useState<QueueSummary>();
  const [cases, setCases] = useState<SupportCase[]>([]);
  const [operators, setOperators] = useState<Operator[]>([]);
  const [selected, setSelected] = useState<CaseDetail>();
  const [reply, setReply] = useState("");
  const [replyStatus, setReplyStatus] = useState<CaseStatus>("waiting_user");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    const [nextSummary, queue, nextOperators] = await Promise.all([
      api<QueueSummary>("/admin/support/summary"),
      api<{ items: SupportCase[] }>("/admin/support/cases"),
      api<{ items: Operator[] }>("/admin/support/operators"),
    ]);
    setSummary(nextSummary);
    setCases(queue.items);
    setOperators(nextOperators.items);
    setError("");
  }

  async function selectCase(caseId: string) {
    const reason = window.prompt("请输入查看玩家支持对话的用途说明：");
    if (!reason || reason.trim().length < 3) return;
    try {
      const detail = await api<CaseDetail>(`/admin/support/cases/${caseId}`, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim() }),
      });
      setSelected(detail);
      setReplyStatus(detail.status === "resolved" || detail.status === "closed" ? "resolved" : "waiting_user");
      setError("");
    } catch (exception) {
      setError((exception as Error).message);
    }
  }

  useEffect(() => {
    Promise.all([
      api<QueueSummary>("/admin/support/summary"),
      api<{ items: SupportCase[] }>("/admin/support/cases"),
      api<{ items: Operator[] }>("/admin/support/operators"),
    ])
      .then(([nextSummary, queue, nextOperators]) => {
        setSummary(nextSummary);
        setCases(queue.items);
        setOperators(nextOperators.items);
        setError("");
      })
      .catch((exception: Error) => setError(exception.message));
  }, []);

  async function updateCase(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    const reason = window.prompt("请输入状态、优先级或分派变更的理由：");
    if (!reason || reason.trim().length < 3) return;
    setBusy(true);
    try {
      await api(`/admin/support/cases/${selected.id}`, {
        method: "PUT",
        body: JSON.stringify({
          status: selected.status,
          priority: selected.priority,
          assigned_to: selected.assigned_to,
          reason: reason.trim(),
        }),
      });
      await Promise.all([load(), selectCase(selected.id)]);
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function sendReply(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    const reason = window.prompt("请输入回复或状态变更的处理说明：");
    if (!reason || reason.trim().length < 3) return;
    setBusy(true);
    try {
      await api(`/admin/support/cases/${selected.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ message: reply, status: replyStatus, reason: reason.trim() }),
      });
      setReply("");
      await Promise.all([load(), selectCase(selected.id)]);
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel stack supportOpsPanel" id="support-operations">
      <div className="entityToolbar">
        <div>
          <h2><Headphones size={19} aria-hidden="true" /> 支持队列</h2>
          <p>账户、余额与故事异常的可审计处理面板；不要在回复中要求密码、验证码或密钥。</p>
        </div>
        <span className={summary?.unassigned_open ? "statusPill pending" : "statusPill live"}>
          {summary?.unassigned_open ? `${summary.unassigned_open} 项未分派` : "队列已分派"}
        </span>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="supportOpsStats">
        <article><span>24 小时新增</span><b>{(summary?.created_24h ?? 0).toLocaleString()}</b></article>
        <article><span>待受理</span><b>{(summary?.by_status.open ?? 0).toLocaleString()}</b></article>
        <article><span>处理中</span><b>{(summary?.by_status.in_progress ?? 0).toLocaleString()}</b></article>
        <article><span>紧急</span><b>{(summary?.by_priority.urgent ?? 0).toLocaleString()}</b></article>
      </div>
      <div className="supportQueueList">
        {cases.length ? cases.map((item) => (
          <button
            key={item.id}
            type="button"
            className={selected?.id === item.id ? "active" : ""}
            onClick={() => void selectCase(item.id)}
          >
            <span>
              <b>{item.subject}</b>
              <small>{item.player.display_name || item.player.email} · {item.category} · {item.message_count} 条消息</small>
            </span>
            <em className={item.priority === "urgent" || item.priority === "high" ? "statusPill pending" : "statusPill live"}>
              {priorityLabels[item.priority]} · {statusLabels[item.status]}
            </em>
          </button>
        )) : <p className="emptyState">目前没有支持请求。</p>}
      </div>
      {selected && (
        <div className="supportOperatorDetail">
          <div className="entityToolbar">
            <div>
              <h3>{selected.subject}</h3>
              <p>{selected.player.display_name || "未命名玩家"} · {selected.player.email}</p>
            </div>
          </div>
          <form className="supportOperatorControls" onSubmit={(event) => void updateCase(event)}>
            <label>
              状态
              <select value={selected.status} onChange={(event) => setSelected({ ...selected, status: event.target.value as CaseStatus })}>
                {Object.entries(statusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            <label>
              优先级
              <select value={selected.priority} onChange={(event) => setSelected({ ...selected, priority: event.target.value as CasePriority })}>
                {Object.entries(priorityLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            <label>
              分派给
              <select value={selected.assigned_to ?? ""} onChange={(event) => setSelected({ ...selected, assigned_to: event.target.value || null })}>
                <option value="">未分派</option>
                {operators.map((operator) => <option key={operator.id} value={operator.id}>{operator.display_name || operator.email}</option>)}
              </select>
            </label>
            <button className="button secondary" disabled={busy}>保存队列设置</button>
          </form>
          <div className="supportMessages operatorThread">
            {selected.messages.map((item) => (
              <article className={item.author_role === "admin" ? "operatorMessage" : "playerMessage"} key={item.id}>
                <b>{item.author_role === "admin" ? "支持团队" : "玩家"}</b>
                <p>{item.body}</p>
                <small>{new Date(item.created_at).toLocaleString("zh-CN")}</small>
              </article>
            ))}
          </div>
          <form className="supportReply" onSubmit={(event) => void sendReply(event)}>
            <label>
              回复后状态
              <select value={replyStatus} onChange={(event) => setReplyStatus(event.target.value as CaseStatus)}>
                <option value="waiting_user">等待玩家回复</option>
                <option value="in_progress">继续处理</option>
                <option value="resolved">标记为已解决</option>
              </select>
            </label>
            <textarea value={reply} minLength={2} maxLength={4000} placeholder="发送给玩家的可见回复" onChange={(event) => setReply(event.target.value)} required />
            <button className="button primary" disabled={busy}><Send size={16} /> {busy ? "正在发送…" : "发送回复"}</button>
          </form>
        </div>
      )}
    </section>
  );
}
