"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import PlatformModelPanel from "@/components/admin/PlatformModelPanel";

type Summary = {
  users: number;
  releases: number;
  pending_moderation: number;
  llm_tokens: number;
  llm_failures: number;
};
type User = {
  id: string;
  email: string;
  display_name: string;
  status: string;
  verified: boolean;
  roles: string[];
  monthly_quota: number;
  monthly_used: number;
  created_at: string;
};
type UserPage = { items: User[]; total: number; limit: number; offset: number };
type FunnelStage = { key: string; label: string; unique_users: number; events: number };
type ProductFunnel = {
  window_days: number;
  consented_users: number;
  events_in_window: number;
  sample_truncated: boolean;
  player: FunnelStage[];
  creator: FunnelStage[];
  daily_active: { date: string; users: number; events: number }[];
};

export default function AdminCenter() {
  const [summary, setSummary] = useState<Summary>();
  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [funnel, setFunnel] = useState<ProductFunnel>();
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  async function load(search = "") {
    const [system, page, productFunnel] = await Promise.all([
      api<Summary>("/admin/system"),
      api<UserPage>(`/admin/users?query=${encodeURIComponent(search)}&limit=50`),
      api<ProductFunnel>("/admin/product-funnel?days=30"),
    ]);
    setSummary(system);
    setUsers(page.items);
    setTotal(page.total);
    setFunnel(productFunnel);
    setError("");
  }
  useEffect(() => {
    Promise.all([
      api<Summary>("/admin/system"),
      api<UserPage>("/admin/users?query=&limit=50"),
      api<ProductFunnel>("/admin/product-funnel?days=30"),
    ])
      .then(([system, page, productFunnel]) => {
        setSummary(system);
        setUsers(page.items);
        setTotal(page.total);
        setFunnel(productFunnel);
        setError("");
      })
      .catch((exception) => setError(exception.message));
  }, []);

  async function search(event: FormEvent) {
    event.preventDefault();
    await load(query);
  }
  async function quota(user: User) {
    const raw = window.prompt(
      `设置 ${user.email} 的月度平台 token 额度：`,
      String(user.monthly_quota),
    );
    if (raw === null) return;
    const monthlyTokens = Number(raw);
    if (!Number.isInteger(monthlyTokens) || monthlyTokens < 0) return;
    const reason = window.prompt("请输入额度调整理由（会写入审计日志）：");
    if (!reason || reason.trim().length < 3) return;
    await api(`/admin/users/${user.id}/quota`, {
      method: "PUT",
      body: JSON.stringify({ monthly_tokens: monthlyTokens, reason }),
    });
    await load(query);
  }
  async function toggleRole(user: User, role: "reviewer" | "admin") {
    const next = new Set(user.roles);
    if (next.has(role)) next.delete(role);
    else next.add(role);
    next.add("player");
    const reason = window.prompt(
      `确认${next.has(role) ? "授予" : "移除"} ${role} 权限，请填写理由：`,
    );
    if (!reason || reason.trim().length < 3) return;
    await api(`/admin/users/${user.id}/roles`, {
      method: "PUT",
      body: JSON.stringify({ roles: [...next], reason }),
    });
    await load(query);
  }

  return (
    <div className="page">
      <div className="pageHead">
        <div>
          <p className="eyebrow">PLATFORM OPERATIONS</p>
          <h1>平台管理中心</h1>
          <p>仅管理员可见。额度与角色变更必须填写理由，并携带请求 ID 写入不可变审计记录。</p>
        </div>
      </div>
      {error && (
        <section className="panel">
          <p className="error" role="alert">
            {error}
          </p>
          <p className="studioHint">如果你不是管理员，这是预期的权限拒绝。</p>
        </section>
      )}
      {!error && (
        <div className="stack">
          <section className="adminStats">
            <article>
              <span>用户</span>
              <b>{summary?.users ?? 0}</b>
            </article>
            <article>
              <span>不可变版本</span>
              <b>{summary?.releases ?? 0}</b>
            </article>
            <article>
              <span>待审核</span>
              <b>{summary?.pending_moderation ?? 0}</b>
            </article>
            <article>
              <span>模型 Token</span>
              <b>{(summary?.llm_tokens ?? 0).toLocaleString()}</b>
            </article>
            <article>
              <span>模型失败</span>
              <b>{summary?.llm_failures ?? 0}</b>
            </article>
          </section>
          <PlatformModelPanel />
          <section className="panel stack">
            <div className="entityToolbar">
              <div>
                <h2>产品体验漏斗</h2>
                <p>最近 {funnel?.window_days ?? 30} 天 · 仅统计主动同意的用户</p>
              </div>
              <span className="healthScore">{funnel?.consented_users ?? 0} 人已同意</span>
            </div>
            <div className="funnelGroups">
              <Funnel title="玩家旅程" stages={funnel?.player ?? []} />
              <Funnel title="创作者旅程" stages={funnel?.creator ?? []} />
            </div>
            <div className="dailyActive">
              <b>每日活跃（匿名聚合）</b>
              <div>
                {funnel?.daily_active.length ? (
                  funnel.daily_active.map((day) => (
                    <span key={day.date} title={`${day.date} · ${day.events} 个事件`}>
                      <small>{day.date.slice(5)}</small>
                      <i style={{ height: `${Math.max(8, Math.min(56, day.users * 8))}px` }} />
                      <strong>{day.users}</strong>
                    </span>
                  ))
                ) : (
                  <p className="studioHint">尚无已同意用户的事件。</p>
                )}
              </div>
            </div>
            <p className="studioHint">
              本页不返回用户身份、输入内容或逐条事件。窗口内共 {funnel?.events_in_window ?? 0}{" "}
              个最小化事件{funnel?.sample_truncated ? "（已达到聚合上限）" : ""}。
            </p>
          </section>
          <section className="panel">
            <div className="entityToolbar">
              <div>
                <h2>账号与额度</h2>
                <p>共 {total} 个账号</p>
              </div>
              <form className="toolbar" onSubmit={search}>
                <input
                  className="input"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="邮箱或显示名"
                />
                <button className="button">搜索</button>
              </form>
            </div>
            <div className="adminUsers">
              {users.map((user) => (
                <article className="adminUser" key={user.id}>
                  <div>
                    <b>{user.display_name || "未设置昵称"}</b>
                    <span>{user.email}</span>
                    <small>
                      {user.status} · {user.verified ? "邮箱已验证" : "邮箱未验证"} ·{" "}
                      {new Date(user.created_at).toLocaleDateString("zh-CN")}
                    </small>
                  </div>
                  <div className="quotaMeter">
                    <span>本月平台额度</span>
                    <progress
                      max={Math.max(1, user.monthly_quota)}
                      value={Math.min(user.monthly_used, user.monthly_quota)}
                    />
                    <small>
                      {user.monthly_used.toLocaleString()} / {user.monthly_quota.toLocaleString()}
                    </small>
                  </div>
                  <div className="roleControls">
                    <button
                      className="button"
                      onClick={() => quota(user).catch((exception) => setError(exception.message))}
                    >
                      调整额度
                    </button>
                    <button
                      className={user.roles.includes("reviewer") ? "roleOn" : ""}
                      onClick={() =>
                        toggleRole(user, "reviewer").catch((exception) =>
                          setError(exception.message),
                        )
                      }
                    >
                      审核员
                    </button>
                    <button
                      className={user.roles.includes("admin") ? "roleOn" : ""}
                      onClick={() =>
                        toggleRole(user, "admin").catch((exception) => setError(exception.message))
                      }
                    >
                      管理员
                    </button>
                  </div>
                  <p className="roleLine">{user.roles.join(" · ")}</p>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function Funnel({ title, stages }: { title: string; stages: FunnelStage[] }) {
  const first = Math.max(stages[0]?.unique_users ?? 0, 1);
  return (
    <div className="funnel">
      <h3>{title}</h3>
      {stages.map((stage, index) => (
        <article key={stage.key}>
          <span>{index + 1}</span>
          <div>
            <b>{stage.label}</b>
            <small>{stage.events} 次事件</small>
          </div>
          <strong>{stage.unique_users} 人</strong>
          <em>{Math.round((stage.unique_users / first) * 100)}%</em>
        </article>
      ))}
    </div>
  );
}
