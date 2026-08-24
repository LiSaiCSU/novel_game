"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BellRing, CheckCheck } from "lucide-react";
import { api } from "@/lib/api";

type Notification = {
  id: string;
  kind: string;
  title: string;
  body: string;
  href: string;
  read_at: string | null;
  created_at: string;
};
type Inbox = { unread_total: number; items: Notification[] };

export default function NotificationsPage() {
  const [inbox, setInbox] = useState<Inbox>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function reload() {
    const result = await api<Inbox>("/notifications");
    setInbox(result);
    setError("");
  }

  useEffect(() => {
    api<Inbox>("/notifications")
      .then((result) => {
        setInbox(result);
        setError("");
      })
      .catch((exception) => setError(exception.message));
  }, []);

  async function markRead(notification: Notification) {
    if (notification.read_at) return;
    try {
      const updated = await api<Notification>(`/notifications/${notification.id}/read`, {
        method: "PUT",
      });
      setInbox(
        (current) =>
          current && {
            unread_total: Math.max(0, current.unread_total - 1),
            items: current.items.map((item) => (item.id === updated.id ? updated : item)),
          },
      );
    } catch (exception) {
      setError((exception as Error).message);
    }
  }

  async function markAllRead() {
    setBusy(true);
    try {
      await api("/notifications/read-all", { method: "POST" });
      await reload();
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !inbox) {
    return (
      <div className="page narrowPage">
        <section className="panel stack">
          <h1>通知中心</h1>
          <p className="error" role="alert">
            {error}
          </p>
          <Link className="button primary" href="/login">
            登录后查看通知
          </Link>
        </section>
      </div>
    );
  }

  return (
    <div className="page notificationsPage">
      <div className="pageHead">
        <div>
          <p className="eyebrow">账户动态</p>
          <h1>通知中心</h1>
          <p>活动权益到账、支持团队回复和重要账户恢复信息都会显示在这里。</p>
        </div>
        <BellRing size={42} aria-hidden="true" />
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <section className="panel stack notificationPanel">
        <div className="entityToolbar">
          <div>
            <h2>{inbox?.unread_total ?? 0} 条未读</h2>
            <p>读取通知只改变你的已读状态，不会删除任何业务账本或支持记录。</p>
          </div>
          {!!inbox?.unread_total && (
            <button className="button secondary" onClick={() => void markAllRead()} disabled={busy}>
              <CheckCheck size={16} /> 全部标为已读
            </button>
          )}
        </div>
        {inbox?.items.length ? (
          <div className="notificationList">
            {inbox.items.map((notification) => (
              <Link
                key={notification.id}
                className={notification.read_at ? "read" : "unread"}
                href={notification.href}
                onClick={() => void markRead(notification)}
              >
                <span>
                  <b>{notification.title}</b>
                  {notification.body && <small>{notification.body}</small>}
                  <time>{new Date(notification.created_at).toLocaleString("zh-CN")}</time>
                </span>
                {!notification.read_at && <i aria-label="未读" />}
              </Link>
            ))}
          </div>
        ) : (
          <p className="emptyState">这里还没有通知。需要帮助时可以前往支持中心提交请求。</p>
        )}
      </section>
    </div>
  );
}
