"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { api } from "@/lib/api";

function ResetForm() {
  const linkToken = useSearchParams().get("token") ?? "";
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    const token = String(d.get("token") || linkToken || "");
    if (!token) {
      setError("请粘贴邮件里的重置令牌，或直接点击邮件中的链接。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token, password: d.get("password") }),
      });
      setDone(true);
    } catch (x) {
      setError((x as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="authShell">
      <form className="authCard stack" onSubmit={submit}>
        <div>
          <p className="eyebrow">重置密码</p>
          <h1>设置新密码</h1>
        </div>
        {!linkToken && (
          <div className="field">
            <label htmlFor="token">重置令牌（邮件链接进入时可留空）</label>
            <input className="input" id="token" name="token" />
          </div>
        )}
        <div className="field">
          <label htmlFor="password">新密码（至少 12 位）</label>
          <input
            className="input"
            id="password"
            name="password"
            type="password"
            minLength={12}
            autoComplete="new-password"
            required
          />
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {done && !error && (
          <p className="success" role="status">
            密码已更新，请重新登录。
          </p>
        )}
        {done ? (
          <Link className="button primary" href="/">
            返回登录
          </Link>
        ) : (
          <button className="button primary" disabled={busy}>
            {busy ? "正在更新…" : "更新密码"}
          </button>
        )}
      </form>
    </div>
  );
}

export default function Reset() {
  return (
    <Suspense fallback={<div className="authShell" />}>
      <ResetForm />
    </Suspense>
  );
}
