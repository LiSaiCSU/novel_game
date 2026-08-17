"use client";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
export default function Register() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const d = new FormData(e.currentTarget);
    const email = String(d.get("email") ?? "");
    try {
      await api("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          email,
          password: d.get("password"),
          display_name: d.get("name"),
        }),
      });
      router.push(`/verify-email?sent=1&email=${encodeURIComponent(email)}`);
      router.refresh();
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
          <p className="eyebrow">创建账户</p>
          <h1>建立你的书架</h1>
          <p className="mutedCopy">保存游玩进度，也可以随时成为创作者。</p>
        </div>
        <div className="field">
          <label htmlFor="name">显示名称</label>
          <input className="input" id="name" name="name" maxLength={80} />
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
        <div className="field">
          <label htmlFor="password">密码（至少 12 个字符）</label>
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
        <button className="button primary" disabled={busy}>
          {busy ? "正在创建…" : "注册账号"}
        </button>
        <p className="authFootnote">
          已有账号？{" "}
          <Link className="textLink" href="/">
            直接登录
          </Link>
        </p>
      </form>
    </div>
  );
}
