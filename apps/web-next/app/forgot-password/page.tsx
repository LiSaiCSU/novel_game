"use client";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
export default function Forgot() {
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const d = new FormData(e.currentTarget);
    try {
      await api("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email: d.get("email") }),
      });
      setDone(true);
    } catch (x) {
      // Rate limits and outages used to reject silently, leaving the form
      // looking as if nothing had been submitted.
      setError((x as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="authShell">
      <form className="authCard stack" onSubmit={submit}>
        <div>
          <p className="eyebrow">找回账户</p>
          <h1>找回密码</h1>
          <p className="mutedCopy">无论账号是否存在，我们都会给出相同响应。</p>
        </div>
        <div className="field">
          <label htmlFor="email">邮箱</label>
          <input
            className="input"
            id="email"
            name="email"
            type="email"
            autoComplete="email"
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
            如果该邮箱已注册，重置邮件已发送。
          </p>
        )}
        <button className="button primary" disabled={busy}>
          {busy ? "正在发送…" : "发送重置邮件"}
        </button>
        <p className="authFootnote">
          <Link className="textLink" href="/login">
            返回登录
          </Link>
        </p>
      </form>
    </div>
  );
}
