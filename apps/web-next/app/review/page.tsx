"use client";

import {useEffect, useState} from "react";
import {api} from "@/lib/api";

type Review = {
  case_id: string;
  release_id: string;
  title: string;
  rating: string;
  evidence: Array<Record<string, unknown>>;
  submitted_at: string;
};
type Report = {
  id: string;
  release_id: string;
  title: string;
  category: string;
  details: string;
  status: string;
  created_at: string;
};
type Audit = {
  id: string;
  action: string;
  actor_id: string | null;
  target_id: string | null;
  request_id: string;
  details: Record<string, unknown>;
  created_at: string;
};

export default function ReviewCenter() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [audits, setAudits] = useState<Audit[]>([]);
  const [error, setError] = useState("");

  const load = () => Promise.all([
    api<Review[]>("/creator/reviews"),
    api<Report[]>("/creator/reports"),
    api<Audit[]>("/creator/audit-logs?limit=50"),
  ]).then(([reviewRows, reportRows, auditRows]) => {
    setReviews(reviewRows);
    setReports(reportRows);
    setAudits(auditRows);
    setError("");
  });

  useEffect(() => { load().catch(exception => setError(exception.message)); }, []);

  async function decideReview(caseId: string, decision: "approved" | "rejected" | "withdrawn") {
    const reason = window.prompt("请输入可供申诉复核的决定理由：");
    if (!reason || reason.trim().length < 3) return;
    await api(`/creator/reviews/${caseId}`, {
      method: "POST", body: JSON.stringify({decision, reason}),
    });
    await load();
  }

  async function decideReport(reportId: string, decision: "investigating" | "resolved" | "dismissed" | "takedown") {
    const note = window.prompt("请输入调查记录或处置依据：");
    if (!note || note.trim().length < 3) return;
    await api(`/creator/reports/${reportId}`, {
      method: "POST", body: JSON.stringify({decision, note}),
    });
    await load();
  }

  return <main className="page">
    <div className="pageHead"><div><p className="eyebrow">TRUST & SAFETY</p><h1>审核与处置中心</h1><p>仅 reviewer/admin 可读取。所有决定、理由与请求 ID 都会进入审计记录。</p></div></div>
    {error && <section className="panel"><p className="error" role="alert">{error}</p><p className="studioHint">如果你不是审核员或管理员，这是预期的权限拒绝。</p></section>}
    {!error && <div className="stack">
      <section className="panel"><h2>待审版本</h2>{reviews.length === 0 ? <p className="studioHint">当前没有待审版本。</p> : reviews.map(item => <article className="releaseRow" key={item.case_id}><div><b>{item.title}</b><small>{item.rating} · {new Date(item.submitted_at).toLocaleString()}</small>{item.evidence.length > 0 && <small>包含申诉材料</small>}</div><div><button className="dangerLink" onClick={() => decideReview(item.case_id, "approved").catch(exception => setError(exception.message))}>通过</button><button className="dangerLink" onClick={() => decideReview(item.case_id, "rejected").catch(exception => setError(exception.message))}>拒绝</button><button className="dangerLink" onClick={() => decideReview(item.case_id, "withdrawn").catch(exception => setError(exception.message))}>紧急下架</button></div></article>)}</section>
      <section className="panel"><h2>举报队列</h2>{reports.length === 0 ? <p className="studioHint">当前没有待处理举报。</p> : reports.map(item => <article className="releaseRow" key={item.id}><div><b>{item.title} · {item.category}</b><small>{item.details}</small><small>{new Date(item.created_at).toLocaleString()}</small></div><div><button className="dangerLink" onClick={() => decideReport(item.id, "investigating").catch(exception => setError(exception.message))}>调查中</button><button className="dangerLink" onClick={() => decideReport(item.id, "dismissed").catch(exception => setError(exception.message))}>驳回</button><button className="dangerLink" onClick={() => decideReport(item.id, "takedown").catch(exception => setError(exception.message))}>下架</button></div></article>)}</section>
      <section className="panel"><h2>最近审计记录</h2>{audits.map(item => <article className="releaseRow" key={item.id}><div><b>{item.action}</b><small>{item.target_id || "-"} · {new Date(item.created_at).toLocaleString()}</small></div><code>{item.request_id}</code></article>)}</section>
    </div>}
  </main>;
}
