"use client";
import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
export default function VerifyEmail() {
  const automaticAttempted = useRef(false);
  const [message, setMessage] = useState(() =>
    typeof location !== "undefined" && new URLSearchParams(location.search).has("sent")
      ? "验证邮件已经发送，请打开邮件中的链接。"
      : "",
  );
  const [verified, setVerified] = useState(false);

  async function verify(token: string) {
    try {
      await api("/auth/verify-email", { method: "POST", body: JSON.stringify({ token }) });
      setVerified(true);
      setMessage("邮箱已验证，现在可以开始游戏和创作。");
    } catch (exception) {
      setMessage((exception as Error).message);
    }
  }

  useEffect(() => {
    const token = new URLSearchParams(location.search).get("token") ?? "";
    if (!token || automaticAttempted.current) return;
    automaticAttempted.current = true;
    void verify(token);
  }, []);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    const token = String(d.get("token") || new URLSearchParams(location.search).get("token") || "");
    await verify(token);
  }
  return (
    <div className="authShell">
      <form className="authCard stack" onSubmit={submit}>
        <div>
          <p className="eyebrow">邮箱验证</p>
          <h1>验证邮箱</h1>
          <p className="mutedCopy">打开邮件中的链接会自动完成验证；也可以在下方手动粘贴令牌。</p>
        </div>
        <div className="field">
          <label htmlFor="token">验证令牌（可选）</label>
          <input className="input" id="token" name="token" />
        </div>
        {message && (
          <p className="success" role="status">
            {message}
          </p>
        )}
        <button className="button primary">完成验证</button>
        {verified && (
          <Link className="button primary" href="/library">
            前往作品库
          </Link>
        )}
      </form>
    </div>
  );
}
