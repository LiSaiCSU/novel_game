"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ChangeEvent, FormEvent, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

const CODE_LENGTH = 4;
const RESEND_COOLDOWN_SECONDS = 60;

type CurrentUser = { email: string; verified: boolean };

function VerifyEmailForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const linkEmail = (searchParams.get("email") ?? "").trim().toLowerCase();
  const justRegistered = searchParams.has("sent");

  // The signed-in address is authoritative — registration already opened a
  // session — so the field only stays editable when there is no session to
  // read an address from.
  const [sessionEmail, setSessionEmail] = useState("");
  const [typedEmail, setTypedEmail] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [verified, setVerified] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const submittedCode = useRef("");

  const email = typedEmail ?? sessionEmail ?? "";
  const address = (email || linkEmail).trim().toLowerCase();
  const shownNotice =
    notice ||
    (justRegistered ? `验证码已发送到你的邮箱，请输入邮件中的 ${CODE_LENGTH} 位数字。` : "");

  useEffect(() => {
    let active = true;
    api<CurrentUser>("/auth/me")
      .then((user) => {
        if (!active) return;
        setSessionEmail(user.email);
        if (user.verified) {
          setVerified(true);
          setNotice("这个邮箱已经完成验证。");
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((seconds) => seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const verify = useCallback(
    async (candidate: string) => {
      if (!address) {
        setError("请先填写注册时使用的邮箱。");
        return;
      }
      setBusy(true);
      setError("");
      try {
        await api("/auth/verify-email", {
          method: "POST",
          body: JSON.stringify({ email: address, code: candidate }),
        });
        setVerified(true);
        setNotice("邮箱已验证，现在可以开始游戏和创作。");
        router.refresh();
      } catch (exception) {
        setCode("");
        submittedCode.current = "";
        setError((exception as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [address, router],
  );

  // Typing the last digit is the natural submit gesture for a code field; the
  // ref keeps a re-render from replaying the same code.
  useEffect(() => {
    if (verified || busy || code.length !== CODE_LENGTH) return;
    if (submittedCode.current === code) return;
    submittedCode.current = code;
    void verify(code);
  }, [code, busy, verified, verify]);

  function onCodeChange(event: ChangeEvent<HTMLInputElement>) {
    setCode(event.target.value.replace(/\D/g, "").slice(0, CODE_LENGTH));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (verified) {
      router.push("/library");
      return;
    }
    if (code.length !== CODE_LENGTH) {
      setError(`请输入 ${CODE_LENGTH} 位数字验证码。`);
      return;
    }
    submittedCode.current = code;
    await verify(code);
  }

  async function resend() {
    if (!address) {
      setError("请先填写注册时使用的邮箱。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api("/auth/verify-email/resend", {
        method: "POST",
        body: JSON.stringify({ email: address }),
      });
      setCode("");
      submittedCode.current = "";
      setCooldown(RESEND_COOLDOWN_SECONDS);
      setNotice("如果这个邮箱还没有验证，新的验证码已经发送。");
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
          <p className="eyebrow">邮箱验证</p>
          <h1>输入验证码</h1>
          <p className="mutedCopy">
            我们向你的邮箱发送了一个 {CODE_LENGTH} 位数字验证码，在下方输入即可完成验证。
          </p>
        </div>
        <div className="field">
          <label htmlFor="email">邮箱</label>
          <input
            className="input"
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            readOnly={!!sessionEmail}
            value={address}
            onChange={(event) => setTypedEmail(event.target.value)}
            required
          />
        </div>
        {!verified && (
          <div className="field">
            <label htmlFor="code">{CODE_LENGTH} 位验证码</label>
            <input
              className="input codeInput"
              id="code"
              name="code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              maxLength={CODE_LENGTH}
              value={code}
              onChange={onCodeChange}
              aria-describedby="code-help"
            />
            <small id="code-help">验证码 15 分钟内有效，连续输错 5 次后需要重新获取。</small>
          </div>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {shownNotice && !error && (
          <p className="success" role="status">
            {shownNotice}
          </p>
        )}
        {verified ? (
          <Link className="button primary" href="/library">
            前往作品库
          </Link>
        ) : (
          <>
            <button className="button primary" disabled={busy || code.length !== CODE_LENGTH}>
              {busy ? "正在验证…" : "完成验证"}
            </button>
            <button
              className="button"
              type="button"
              disabled={busy || cooldown > 0}
              onClick={() => void resend()}
            >
              {cooldown > 0 ? `重新发送验证码（${cooldown}s）` : "重新发送验证码"}
            </button>
          </>
        )}
      </form>
    </div>
  );
}

export default function VerifyEmail() {
  return (
    <Suspense fallback={<div className="authShell" />}>
      <VerifyEmailForm />
    </Suspense>
  );
}
