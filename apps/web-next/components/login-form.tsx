"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";

function safeNextPath(): string {
  if (typeof window === "undefined") return "/play";
  const requested = new URLSearchParams(window.location.search).get("next") ?? "";
  return requested.startsWith("/") && !requested.startsWith("//") ? requested : "/play";
}

export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    api("/auth/me")
      .then(() => {
        if (active) router.replace(safeNextPath());
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [router]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: data.get("email"), password: data.get("password") }),
      });
      router.push(safeNextPath());
      router.refresh();
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="authShell">
      <form className="authCard stack" onSubmit={submit}>
        <div>
          <p className="eyebrow">WELCOME BACK</p>
          <h1>继续你的故事</h1>
          <p className="mutedCopy">登录后，你的世界、模型设置与存档只属于这个账号。</p>
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
          <label htmlFor="password">密码</label>
          <input
            className="input"
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="button primary" disabled={busy}>
          {busy ? "正在登录…" : "登录"}
        </button>
        <p className="authFootnote">
          <Link className="textLink" href="/forgot-password">
            忘记密码？
          </Link>
        </p>
        <p className="authFootnote">
          还没有账号？{" "}
          <Link className="textLink" href="/register">
            免费注册
          </Link>
        </p>
      </form>
    </div>
  );
}
