"use client";

import { useState } from "react";
import { api } from "@/lib/api";

type User = {
  id: string;
  email: string;
  display_name: string;
  status: string;
  verified: boolean;
};

type Playthrough = {
  id: string;
  release_id: string;
  status: string;
  turn_number: number;
  updated_at: string;
};

type Inspection = { playthroughs: Playthrough[] };
type Chapter = { kind: string; text: string };

/**
 * The per-account controls that can actually hurt.
 *
 * Each one asks for a reason, because the server requires one and because
 * being made to type why you are doing something is a real check on doing it
 * absent-mindedly. Deletion additionally asks for the address, since the id
 * on screen is easy to have scrolled past.
 */
export default function UserActions({
  user,
  onChanged,
  onError,
}: {
  user: User;
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [inspection, setInspection] = useState<Inspection>();
  const [chapters, setChapters] = useState<Chapter[]>();

  function reasonFor(what: string): string | undefined {
    const reason = window.prompt(`${what}\n请填写理由（会写入审计日志）：`);
    if (!reason || reason.trim().length < 3) return undefined;
    return reason;
  }

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    try {
      await work();
      onChanged();
    } catch (exception) {
      onError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function suspend(suspended: boolean) {
    const reason = reasonFor(suspended ? `封禁 ${user.email}` : `解封 ${user.email}`);
    if (!reason) return;
    await run(() =>
      api(`/admin/users/${user.id}/suspend`, {
        method: "POST",
        body: JSON.stringify({ suspended, reason }),
      }),
    );
  }

  async function simple(path: string, what: string) {
    const reason = reasonFor(`${what}：${user.email}`);
    if (!reason) return;
    await run(() =>
      api(`/admin/users/${user.id}/${path}`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
    );
  }

  async function remove() {
    const reason = reasonFor(`永久删除 ${user.email} 及其全部数据（不可恢复）`);
    if (!reason) return;
    const typed = window.prompt(`确认删除，请完整输入该账号的邮箱：\n${user.email}`);
    if (typed?.trim().toLowerCase() !== user.email.toLowerCase()) return;
    await run(() =>
      api(`/admin/users/${user.id}/delete`, {
        method: "POST",
        body: JSON.stringify({ reason, confirm_email: typed }),
      }),
    );
  }

  async function inspect() {
    const reason = reasonFor(`以只读方式查看 ${user.email} 的存档`);
    if (!reason) return;
    setBusy(true);
    setChapters(undefined);
    try {
      setInspection(
        await api<Inspection>(`/admin/users/${user.id}/inspect`, {
          method: "POST",
          body: JSON.stringify({ reason }),
        }),
      );
    } catch (exception) {
      onError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function adjustWallet() {
    const raw = window.prompt(`调整 ${user.email} 的叙点余额（正数发放，负数扣减）`, "100");
    if (raw === null) return;
    const creditDelta = Number(raw);
    if (!Number.isSafeInteger(creditDelta) || creditDelta === 0) return;
    const reason = reasonFor(`${creditDelta > 0 ? "发放" : "扣减"} ${user.email} 的叙点`);
    if (!reason) return;
    if (
      !window.confirm(
        `确认${creditDelta > 0 ? "发放" : "扣减"} ${Math.abs(creditDelta).toLocaleString()} 叙点？此操作会写入不可变账本。`,
      )
    )
      return;
    await run(() =>
      api(`/admin/commerce/users/${user.id}/adjustments`, {
        method: "POST",
        body: JSON.stringify({
          credit_delta: creditDelta,
          reason,
          entry_type: creditDelta > 0 ? "grant" : "adjustment",
          idempotency_key: crypto.randomUUID(),
        }),
      }),
    );
  }

  async function openStory(playthroughId: string) {
    const reason = reasonFor(`查看 ${user.email} 的故事正文（只读）`);
    if (!reason) return;
    setBusy(true);
    try {
      const detail = await api<{ chapters: Chapter[] }>(
        `/admin/users/${user.id}/inspect/${playthroughId}`,
        {
          method: "POST",
          body: JSON.stringify({ reason }),
        },
      );
      setChapters(detail.chapters);
    } catch (exception) {
      onError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className="dangerLink userActionsToggle" onClick={() => setOpen(true)}>
        更多操作
      </button>
    );
  }

  return (
    <div className="userActions">
      <div className="toolbar">
        {user.status === "suspended" ? (
          <button type="button" disabled={busy} onClick={() => void suspend(false)}>
            解封
          </button>
        ) : (
          <button type="button" disabled={busy} onClick={() => void suspend(true)}>
            封禁
          </button>
        )}
        <button type="button" disabled={busy} onClick={() => void simple("revoke-sessions", "强制下线所有会话")}>
          强制下线
        </button>
        {!user.verified && (
          <button type="button" disabled={busy} onClick={() => void simple("verify-email", "标记邮箱已验证")}>
            标记已验证
          </button>
        )}
        <button type="button" disabled={busy} onClick={() => void simple("usage/reset", "重置本月用量")}>
          重置本月用量
        </button>
        <button type="button" disabled={busy} onClick={() => void adjustWallet()}>
          调整叙点
        </button>
        <button type="button" disabled={busy} onClick={() => void inspect()}>
          只读查看存档
        </button>
        <button type="button" className="destructive" disabled={busy} onClick={() => void remove()}>
          永久删除
        </button>
        <button type="button" onClick={() => setOpen(false)}>
          收起
        </button>
      </div>

      {inspection && (
        <div className="inspection">
          <p className="studioHint">
            只读。该玩家可以在自己的账户设置里看到这次查看记录。
          </p>
          {inspection.playthroughs.length === 0 && <p className="studioHint">这个账号还没有存档。</p>}
          {inspection.playthroughs.map((play) => (
            <button
              type="button"
              key={play.id}
              className="inspectionRow"
              disabled={busy}
              onClick={() => void openStory(play.id)}
            >
              <span>{play.id.slice(0, 8)}</span>
              <small>
                {play.status} · 第 {play.turn_number} 回合
              </small>
            </button>
          ))}
          {chapters?.map((chapter, index) => (
            <blockquote key={index} className="inspectionChapter">
              {chapter.text}
            </blockquote>
          ))}
        </div>
      )}
    </div>
  );
}
