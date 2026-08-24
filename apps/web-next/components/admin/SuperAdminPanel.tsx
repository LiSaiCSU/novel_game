"use client";

import { FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";

type Candidate = {
  id: string;
  email: string;
  display_name: string;
  status: string;
  roles: string[];
};

type SuperAdmin = {
  id: string;
  email: string;
  display_name: string;
  status: string;
  granted_at: string;
};

type PendingApproval = {
  id: string;
  requester_id: string;
  requester_email: string;
  target_user_id: string;
  target_email: string;
  requested_enabled: boolean;
  reason: string;
  expires_at: string;
  created_at: string;
};
type Governance = {
  items: SuperAdmin[];
  pending_approvals: PendingApproval[];
  current_user_id: string;
  mfa_required: boolean;
};

/** A narrow, deliberate surface for the platform's break-glass role. */
export default function SuperAdminPanel({ users }: { users: Candidate[] }) {
  const [governance, setGovernance] = useState<Governance>();
  const [targetId, setTargetId] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    const result = await api<Governance>("/admin/governance/super-admins");
    setGovernance(result);
    setError("");
  }

  useEffect(() => {
    api<Governance>("/admin/governance/super-admins")
      .then((result) => {
        setGovernance(result);
        setError("");
      })
      .catch((exception: unknown) => {
        // Ordinary administrators should not be told who has break-glass
        // access. A 403 is the expected absence of this panel.
        if (exception instanceof ApiError && exception.status === 403) return;
        setError((exception as Error).message);
      });
  }, []);

  async function setRole(userId: string, enabled: boolean, operationReason: string) {
    if (operationReason.trim().length < 3) return;
    setBusy(true);
    try {
      await api(`/admin/users/${userId}/super-admin`, {
        method: "PUT",
        body: JSON.stringify({ enabled, reason: operationReason.trim() }),
      });
      setReason("");
      await load();
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function grant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!targetId) return;
    await setRole(targetId, true, reason);
  }

  async function review(approval: PendingApproval, decision: "approve" | "reject" | "cancel") {
    const action = decision === "approve" ? "批准" : decision === "reject" ? "拒绝" : "撤回";
    const decisionReason = window.prompt(`请填写${action}此最高权限请求的理由：`);
    if (!decisionReason || decisionReason.trim().length < 3) return;
    setBusy(true);
    try {
      await api(`/admin/governance/super-admin-approvals/${approval.id}/${decision}`, {
        method: "POST",
        body: JSON.stringify({ reason: decisionReason.trim() }),
      });
      await load();
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!governance && !error) return null;
  if (!governance)
    return (
      <section className="panel stack">
        <p className="error" role="alert">
          {error}
        </p>
      </section>
    );

  const candidates = users.filter(
    (user) => user.status === "active" && !governance.items.some((item) => item.id === user.id),
  );

  return (
    <section className="panel stack superAdminPanel">
      <div className="entityToolbar">
        <div>
          <p className="eyebrow">最高权限治理</p>
          <h2>超级管理员</h2>
          <p>仅限已完成 MFA step-up 的超级管理员。任何授予或撤销均需另一名超级管理员复核。</p>
        </div>
        <span className="statusPill live">{governance.items.length} 名受保护管理员</span>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="superAdminList">
        {governance.items.map((item) => (
          <article key={item.id}>
            <div>
              <b>{item.display_name || item.email}</b>
              <span>{item.email}</span>
              <small>授予于 {new Date(item.granted_at).toLocaleString("zh-CN")}</small>
            </div>
            {item.id === governance.current_user_id ? (
              <span className="statusPill live">当前登录账户</span>
            ) : (
              <button
                type="button"
                className="destructive"
                disabled={busy}
                onClick={() => {
                  const revokeReason = window.prompt(
                    `撤销 ${item.email} 的超级管理员权限。请说明原因：`,
                  );
                  if (revokeReason) void setRole(item.id, false, revokeReason);
                }}
              >
                发起撤销复核
              </button>
            )}
          </article>
        ))}
      </div>
      <div className="superAdminApprovals">
        <h3>待复核请求</h3>
        {governance.pending_approvals.length ? (
          governance.pending_approvals.map((approval) => {
            const ownRequest = approval.requester_id === governance.current_user_id;
            return (
              <article key={approval.id}>
                <div>
                  <b>{approval.requested_enabled ? "授予最高权限" : "撤销最高权限"}</b>
                  <span>
                    {approval.target_email} · 由 {approval.requester_email} 发起
                  </span>
                  <small>
                    {approval.reason} · {new Date(approval.expires_at).toLocaleString("zh-CN")}{" "}
                    前有效
                  </small>
                </div>
                <div className="superAdminApprovalActions">
                  {ownRequest ? (
                    <button
                      type="button"
                      className="button secondary"
                      disabled={busy}
                      onClick={() => void review(approval, "cancel")}
                    >
                      撤回请求
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="button primary"
                        disabled={busy}
                        onClick={() => void review(approval, "approve")}
                      >
                        批准并执行
                      </button>
                      <button
                        type="button"
                        className="button secondary"
                        disabled={busy}
                        onClick={() => void review(approval, "reject")}
                      >
                        拒绝
                      </button>
                    </>
                  )}
                </div>
              </article>
            );
          })
        ) : (
          <p className="emptyState">目前没有等待另一名超级管理员复核的请求。</p>
        )}
      </div>
      <form className="superAdminGrant" onSubmit={(event) => void grant(event)}>
        <select
          value={targetId}
          onChange={(event) => setTargetId(event.target.value)}
          aria-label="选择要授予最高权限的账户"
        >
          <option value="">选择已加载的活跃账户</option>
          {candidates.map((user) => (
            <option key={user.id} value={user.id}>
              {user.display_name || user.email} · {user.email}
            </option>
          ))}
        </select>
        <input
          className="input"
          value={reason}
          minLength={3}
          maxLength={500}
          placeholder="申请理由（写入不可变审计日志）"
          onChange={(event) => setReason(event.target.value)}
          required
        />
        <button className="button primary" disabled={busy || !targetId}>
          提交双人审批
        </button>
      </form>
      <p className="studioHint">
        请求 24
        小时后自动失效；发起人不能自行批准，最后一名超级管理员也不能被撤销。首次授予只能通过部署环境的
        `SUPER_ADMIN_EMAILS` 引导，不能由普通管理后台发起。
      </p>
    </section>
  );
}
