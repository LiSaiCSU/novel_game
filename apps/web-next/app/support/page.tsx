"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { CircleHelp, MessageCircleMore, Send } from "lucide-react";
import { api } from "@/lib/api";

type CaseStatus = "open" | "in_progress" | "waiting_user" | "resolved" | "closed";
type CaseCategory = "account" | "billing" | "playthrough" | "technical" | "content" | "other";

type SupportCase = {
  id: string;
  playthrough_id: string | null;
  category: CaseCategory;
  status: CaseStatus;
  priority: string;
  subject: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  latest_message_at: string | null;
  player_can_reply: boolean;
};

type SupportMessage = {
  id: string;
  author_role: "player" | "admin";
  body: string;
  created_at: string;
};

type SupportDetail = SupportCase & { messages: SupportMessage[] };

const categoryLabels: Record<CaseCategory, string> = {
  account: "账户与登录",
  billing: "余额与计费",
  playthrough: "故事卡住或异常",
  technical: "技术问题",
  content: "内容与安全",
  other: "其他问题",
};
const statusLabels: Record<CaseStatus, string> = {
  open: "等待受理",
  in_progress: "正在处理",
  waiting_user: "等待你的回复",
  resolved: "已解决",
  closed: "已关闭",
};

export default function SupportPage() {
  const [cases, setCases] = useState<SupportCase[]>([]);
  const [selected, setSelected] = useState<SupportDetail>();
  const [category, setCategory] = useState<CaseCategory>("playthrough");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function loadCases() {
    const result = await api<{ items: SupportCase[] }>("/support/cases");
    setCases(result.items);
    setError("");
  }

  async function openCase(caseId: string) {
    try {
      const result = await api<SupportDetail>(`/support/cases/${caseId}`);
      setSelected(result);
      setReply("");
      setError("");
    } catch (exception) {
      setError((exception as Error).message);
    }
  }

  useEffect(() => {
    api<{ items: SupportCase[] }>("/support/cases")
      .then((result) => {
        setCases(result.items);
        setError("");
      })
      .catch((exception) => setError(exception.message));
  }, []);

  async function createCase(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const created = await api<SupportDetail>("/support/cases", {
        method: "POST",
        body: JSON.stringify({ category, subject, message }),
      });
      setSubject("");
      setMessage("");
      setSelected(created);
      setNotice("问题已提交。你可以在这里查看处理进度并补充信息。");
      await loadCases();
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function sendReply(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    try {
      await api(`/support/cases/${selected.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ message: reply }),
      });
      setReply("");
      setNotice("补充信息已发送给处理人员。");
      await Promise.all([loadCases(), openCase(selected.id)]);
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !cases.length && !selected) {
    return (
      <div className="page narrowPage">
        <section className="panel stack">
          <h1>帮助与支持</h1>
          <p className="error" role="alert">{error}</p>
          <Link className="button primary" href="/login">登录后获取帮助</Link>
        </section>
      </div>
    );
  }

  return (
    <div className="page supportPage">
      <div className="pageHead">
        <div>
          <p className="eyebrow">帮助与恢复</p>
          <h1>支持中心</h1>
          <p>遇到账户、余额或故事异常时，在这里提交可追踪的问题。不会自动附带故事正文、密钥或设备信息。</p>
        </div>
        <CircleHelp size={42} aria-hidden="true" />
      </div>
      {notice && <p className="success" role="status">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}

      <div className="supportGrid">
        <section className="panel stack supportCreate">
          <div>
            <h2><MessageCircleMore size={19} aria-hidden="true" /> 提交问题</h2>
            <p className="studioHint">请不要在工单里提供密码、验证码、完整 API 密钥或支付卡号。</p>
          </div>
          <form className="supportForm" onSubmit={(event) => void createCase(event)}>
            <label>
              问题类别
              <select value={category} onChange={(event) => setCategory(event.target.value as CaseCategory)}>
                {Object.entries(categoryLabels).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </label>
            <label>
              简短标题
              <input
                value={subject}
                minLength={3}
                maxLength={140}
                placeholder="例如：选择行动后故事没有继续"
                onChange={(event) => setSubject(event.target.value)}
                required
              />
            </label>
            <label>
              发生了什么
              <textarea
                value={message}
                minLength={5}
                maxLength={4000}
                placeholder="请描述操作步骤、看到的提示，以及你希望如何恢复。"
                onChange={(event) => setMessage(event.target.value)}
                required
              />
            </label>
            <button className="button primary" disabled={busy}>{busy ? "正在提交…" : "提交支持请求"}</button>
          </form>
        </section>

        <section className="panel stack supportCases">
          <div className="entityToolbar">
            <div>
              <h2>我的请求</h2>
              <p>处理进度和回复只对你的账号可见。</p>
            </div>
            <span className="healthScore">{cases.length}</span>
          </div>
          {cases.length ? (
            <div className="supportCaseList">
              {cases.map((item) => (
                <button
                  className={selected?.id === item.id ? "active" : ""}
                  key={item.id}
                  type="button"
                  onClick={() => void openCase(item.id)}
                >
                  <span>
                    <b>{item.subject}</b>
                    <small>{categoryLabels[item.category]} · {item.message_count} 条消息</small>
                  </span>
                  <em className={item.status === "waiting_user" ? "statusPill pending" : "statusPill live"}>
                    {statusLabels[item.status]}
                  </em>
                </button>
              ))}
            </div>
          ) : (
            <p className="emptyState">还没有支持请求。账户密码可通过登录页的“忘记密码”自助重置。</p>
          )}
        </section>
      </div>

      {selected && (
        <section className="panel stack supportThread">
          <div className="entityToolbar">
            <div>
              <p className="eyebrow">{categoryLabels[selected.category]}</p>
              <h2>{selected.subject}</h2>
            </div>
            <span className={selected.status === "waiting_user" ? "statusPill pending" : "statusPill live"}>
              {statusLabels[selected.status]}
            </span>
          </div>
          <div className="supportMessages">
            {selected.messages.map((item) => (
              <article className={item.author_role === "player" ? "playerMessage" : "operatorMessage"} key={item.id}>
                <b>{item.author_role === "player" ? "你" : "支持团队"}</b>
                <p>{item.body}</p>
                <small>{new Date(item.created_at).toLocaleString("zh-CN")}</small>
              </article>
            ))}
          </div>
          {selected.player_can_reply ? (
            <form className="supportReply" onSubmit={(event) => void sendReply(event)}>
              <textarea
                value={reply}
                minLength={2}
                maxLength={4000}
                placeholder="补充信息或回复支持团队"
                onChange={(event) => setReply(event.target.value)}
                required
              />
              <button className="button primary" disabled={busy}>
                <Send size={16} /> {busy ? "正在发送…" : "发送回复"}
              </button>
            </form>
          ) : (
            <p className="studioHint">此请求已结束。如有新的问题，请提交新的支持请求。</p>
          )}
        </section>
      )}
    </div>
  );
}
