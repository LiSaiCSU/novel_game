"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";

type Announcement = { message: string; level: "info" | "warning" | "maintenance"; active: boolean };
type PlatformSettings = { default_quota: { monthly_tokens: number }; announcement: Announcement };
type BulkPreview = { matched: number; sample: string[] };

const scopes = [
  { key: "all", label: "全部账号" },
  { key: "role", label: "按角色" },
  { key: "search", label: "按搜索" },
] as const;

const roles = ["player", "creator", "reviewer", "admin"] as const;

/**
 * Platform-wide operations: the quota every new account starts with, one quota
 * applied across a whole population, and the notice every player sees.
 *
 * The bulk control deliberately makes you look before you leap. The count is
 * fetched first and sent back with the change; if the population moved in
 * between, the server refuses rather than applying one number to a different
 * set of people than the one that was on screen.
 */
export default function PlatformOpsPanel({ onChanged }: { onChanged: () => void }) {
  const [settings, setSettings] = useState<PlatformSettings>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const [scope, setScope] = useState<(typeof scopes)[number]["key"]>("all");
  const [role, setRole] = useState<(typeof roles)[number]>("player");
  const [query, setQuery] = useState("");
  const [bulkTokens, setBulkTokens] = useState("500000");
  const [bulkReason, setBulkReason] = useState("");
  const [preview, setPreview] = useState<BulkPreview>();

  useEffect(() => {
    api<PlatformSettings>("/admin/settings")
      .then(setSettings)
      .catch((exception: Error) => setError(exception.message));
  }, []);

  function search(): string {
    if (scope === "role") return `scope=role&role=${role}`;
    if (scope === "search") return `scope=search&query=${encodeURIComponent(query)}`;
    return "scope=all";
  }

  async function runPreview() {
    setError("");
    setPreview(undefined);
    try {
      setPreview(await api<BulkPreview>(`/admin/users/quota/bulk/preview?${search()}`));
    } catch (exception) {
      setError((exception as Error).message);
    }
  }

  async function applyBulk() {
    if (!preview) return;
    const tokens = Number(bulkTokens);
    if (!Number.isInteger(tokens) || tokens < 0) {
      setError("额度必须是不小于 0 的整数。");
      return;
    }
    if (bulkReason.trim().length < 3) {
      setError("请填写调整理由，它会写入审计日志。");
      return;
    }
    if (
      !window.confirm(
        `将 ${preview.matched} 个账号的月度额度统一设为 ${tokens.toLocaleString()}？此操作会立即生效。`,
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ affected: number }>("/admin/users/quota/bulk", {
        method: "POST",
        body: JSON.stringify({
          monthly_tokens: tokens,
          reason: bulkReason,
          scope,
          role: scope === "role" ? role : null,
          query: scope === "search" ? query : "",
          expect_users: preview.matched,
        }),
      });
      setNotice(`已调整 ${result.affected} 个账号的额度。`);
      setPreview(undefined);
      setBulkReason("");
      onChanged();
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveDefaultQuota(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const tokens = Number(data.get("tokens"));
    const reason = String(data.get("reason") ?? "");
    if (!Number.isInteger(tokens) || tokens < 0 || reason.trim().length < 3) {
      setError("请填写有效的额度和理由。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api("/admin/settings/default-quota", {
        method: "PUT",
        body: JSON.stringify({ monthly_tokens: tokens, reason }),
      });
      setSettings(await api<PlatformSettings>("/admin/settings"));
      setNotice("新用户默认额度已更新，已有账号不受影响。");
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveAnnouncement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const reason = String(data.get("reason") ?? "");
    if (reason.trim().length < 3) {
      setError("请填写发布理由。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api("/admin/settings/announcement", {
        method: "PUT",
        body: JSON.stringify({
          message: String(data.get("message") ?? ""),
          level: String(data.get("level") ?? "info"),
          active: data.get("active") === "on",
          reason,
        }),
      });
      setSettings(await api<PlatformSettings>("/admin/settings"));
      setNotice("全站公告已更新。");
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel stack">
      <div>
        <p className="eyebrow">平台运营</p>
        <h2>额度与公告</h2>
        <p className="studioHint">
          所有改动都会带上理由和请求 ID 写入审计日志。批量额度需要先读取数量再提交。
        </p>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && !error && (
        <p className="success" role="status">
          {notice}
        </p>
      )}

      <h3 className="railSection">批量设置额度</h3>
      <div className="field">
        <label htmlFor="bulk-scope">调整范围</label>
        <select
          className="select"
          id="bulk-scope"
          value={scope}
          onChange={(event) => {
            setScope(event.target.value as typeof scope);
            setPreview(undefined);
          }}
        >
          {scopes.map((item) => (
            <option key={item.key} value={item.key}>
              {item.label}
            </option>
          ))}
        </select>
      </div>
      {scope === "role" && (
        <div className="field">
          <label htmlFor="bulk-role">角色</label>
          <select
            className="select"
            id="bulk-role"
            value={role}
            onChange={(event) => {
              setRole(event.target.value as typeof role);
              setPreview(undefined);
            }}
          >
            {roles.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
      )}
      {scope === "search" && (
        <div className="field">
          <label htmlFor="bulk-query">邮箱或昵称包含</label>
          <input
            className="input"
            id="bulk-query"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPreview(undefined);
            }}
          />
        </div>
      )}
      <div className="field">
        <label htmlFor="bulk-tokens">月度 token 额度</label>
        <input
          className="input"
          id="bulk-tokens"
          inputMode="numeric"
          value={bulkTokens}
          onChange={(event) => setBulkTokens(event.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="bulk-reason">调整理由（写入审计日志）</label>
        <input
          className="input"
          id="bulk-reason"
          value={bulkReason}
          onChange={(event) => setBulkReason(event.target.value)}
        />
      </div>
      <div className="toolbar">
        <button type="button" className="button" disabled={busy} onClick={() => void runPreview()}>
          先看影响范围
        </button>
        <button
          type="button"
          className="button primary"
          disabled={busy || !preview}
          onClick={() => void applyBulk()}
        >
          {preview ? `确认调整 ${preview.matched} 个账号` : "确认调整"}
        </button>
      </div>
      {preview && (
        <p className="studioHint">
          将影响 <b>{preview.matched}</b> 个账号
          {preview.sample.length > 0 && <>，例如：{preview.sample.join("、")}</>}
        </p>
      )}

      <h3 className="railSection">新用户默认额度</h3>
      <form className="stack" onSubmit={saveDefaultQuota}>
        <div className="field">
          <label htmlFor="default-tokens">默认月度 token 额度</label>
          <input
            className="input"
            id="default-tokens"
            name="tokens"
            inputMode="numeric"
            defaultValue={settings?.default_quota.monthly_tokens ?? 200000}
            key={settings?.default_quota.monthly_tokens}
          />
          <small>只影响之后注册的账号。</small>
        </div>
        <div className="field">
          <label htmlFor="default-reason">理由</label>
          <input className="input" id="default-reason" name="reason" />
        </div>
        <button className="button primary" disabled={busy}>
          保存默认额度
        </button>
      </form>

      <h3 className="railSection">全站公告</h3>
      <form className="stack" onSubmit={saveAnnouncement}>
        <div className="field">
          <label htmlFor="announce-message">公告内容</label>
          <textarea
            className="textarea"
            id="announce-message"
            name="message"
            maxLength={500}
            defaultValue={settings?.announcement.message ?? ""}
            key={settings?.announcement.message}
          />
          <small>留空即撤下公告。所有登录玩家都会看到。</small>
        </div>
        <div className="field">
          <label htmlFor="announce-level">级别</label>
          <select
            className="select"
            id="announce-level"
            name="level"
            defaultValue={settings?.announcement.level ?? "info"}
            key={settings?.announcement.level}
          >
            <option value="info">通知</option>
            <option value="warning">警告</option>
            <option value="maintenance">维护</option>
          </select>
        </div>
        <label className="checkRow" htmlFor="announce-active">
          <input
            type="checkbox"
            id="announce-active"
            name="active"
            defaultChecked={settings?.announcement.active ?? false}
            key={String(settings?.announcement.active)}
          />
          <span>立即发布</span>
        </label>
        <div className="field">
          <label htmlFor="announce-reason">理由</label>
          <input className="input" id="announce-reason" name="reason" />
        </div>
        <button className="button primary" disabled={busy}>
          保存公告
        </button>
      </form>
    </section>
  );
}
