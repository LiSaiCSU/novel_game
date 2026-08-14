"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

type Credential = {
  provider: string;
  model: string;
  hint: string;
  status: string;
  base_url: string;
};
type Usage = {
  daily: { used: number; limit: number };
  monthly: { used: number; limit: number };
  turn_limit: number;
};
type Session = {
  id: string;
  user_agent: string;
  ip_address: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  current: boolean;
};
type MfaStatus = {
  enabled: boolean;
  required_for_admin: boolean;
  step_up_valid: boolean;
  recovery_codes_remaining: number;
};
type MfaEnrollment = { secret: string; otpauth_uri: string };
type Privacy = {
  product_analytics: boolean;
  consent_updated_at?: string | null;
  collection: { events: string; never: string[]; retention: string };
};

export default function Settings() {
  const router = useRouter();
  const [keys, setKeys] = useState<Credential[]>([]);
  const [usage, setUsage] = useState<Usage>();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [mfa, setMfa] = useState<MfaStatus>();
  const [privacy, setPrivacy] = useState<Privacy>();
  const [mfaEnrollment, setMfaEnrollment] = useState<MfaEnrollment>();
  const [mfaPassword, setMfaPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [providerPreset, setProviderPreset] = useState("compatible:deepseek");
  const [baseUrl, setBaseUrl] = useState("https://api.deepseek.com");

  function chooseProvider(value: string) {
    setProviderPreset(value);
    if (value === "compatible:deepseek") setBaseUrl("https://api.deepseek.com");
    else if (value === "compatible:volcengine")
      setBaseUrl("https://ark.cn-beijing.volces.com/api/v3");
    else setBaseUrl("");
  }

  const load = () =>
    Promise.all([
      api<Credential[]>("/settings/llm-credentials"),
      api<Usage>("/settings/llm-usage"),
      api<Session[]>("/auth/sessions"),
      api<MfaStatus>("/auth/mfa"),
      api<Privacy>("/settings/privacy"),
    ]).then(([credentials, nextUsage, devices, mfaStatus, privacyPreferences]) => {
      setKeys(credentials);
      setUsage(nextUsage);
      setSessions(devices);
      setMfa(mfaStatus);
      setPrivacy(privacyPreferences);
    });

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const selected = String(data.get("provider_preset") ?? "openai");
    const provider = selected.startsWith("compatible:") ? "compatible" : selected;
    try {
      await api("/settings/llm-credentials", {
        method: "PUT",
        body: JSON.stringify({
          provider,
          model: data.get("model"),
          secret: data.get("secret"),
          base_url: provider === "compatible" ? data.get("base_url") : "",
        }),
      });
      setMessage("密钥已加密保存；平台不会回显完整内容。");
      await load();
      form.reset();
      chooseProvider("compatible:deepseek");
    } catch (exception) {
      setMessage((exception as Error).message);
    }
  }

  async function remove(provider: string) {
    await api(`/settings/llm-credentials/${provider}`, { method: "DELETE" });
    setMessage("密钥已删除。");
    await load();
  }

  async function testKey(provider: string) {
    setMessage("正在测试连接；这会产生一次极小的模型调用…");
    const result = await api<{ model: string; latency_ms: number }>(
      `/settings/llm-credentials/${provider}/test`,
      { method: "POST" },
    );
    setMessage(`连接成功：${result.model}，${result.latency_ms} ms。`);
  }

  async function revoke(session: Session) {
    await api(`/auth/sessions/${session.id}`, { method: "DELETE" });
    setMessage(session.current ? "当前设备已退出。" : "设备会话已撤销。");
    if (session.current) router.push("/login");
    else await load();
  }

  async function exportData() {
    type ExportJob = {
      id: string;
      status: string;
      download_url?: string | null;
      error_code?: string;
    };
    setMessage("正在生成完整个人数据制品；作品较多时可能需要一点时间…");
    let job = await api<ExportJob>("/settings/data-exports", { method: "POST" });
    for (
      let attempt = 0;
      attempt < 60 && ["queued", "processing"].includes(job.status);
      attempt += 1
    ) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      job = await api<ExportJob>(`/settings/data-exports/${job.id}`);
    }
    if (job.status !== "ready" || !job.download_url)
      throw new Error(
        job.error_code ? `导出失败：${job.error_code}` : "导出仍在处理中，请稍后重试",
      );
    const anchor = document.createElement("a");
    anchor.href = job.download_url;
    anchor.download = "narrative-data-export.json";
    anchor.click();
    setMessage("个人数据制品已生成，下载链接将在 24 小时后失效。");
  }

  async function deleteAccount() {
    if (!window.confirm("账号将立即退出，并在 30 天后删除。确定继续吗？")) return;
    await api("/settings/account", { method: "DELETE" });
    router.push("/");
  }

  async function updateAnalytics(enabled: boolean) {
    const next = await api<Privacy>("/settings/privacy", {
      method: "PUT",
      body: JSON.stringify({ product_analytics: enabled }),
    });
    setPrivacy(next);
    setMessage(
      enabled
        ? "已开启匿名产品改进数据。不会收集游戏输入、生成正文、邮箱、密钥或 IP。"
        : "已关闭产品改进数据，并删除此前保存的产品分析事件。",
    );
  }

  async function startMfa() {
    const enrollment = await api<MfaEnrollment>("/auth/mfa/enroll", {
      method: "POST",
      body: JSON.stringify({ password: mfaPassword }),
    });
    setMfaEnrollment(enrollment);
    setMfaPassword("");
    setRecoveryCodes([]);
    setMessage("请把密钥加入验证器，再输入当前六位验证码确认。密钥只在这一步显示。");
  }

  async function confirmMfa() {
    const result = await api<{ recovery_codes: string[] }>("/auth/mfa/confirm", {
      method: "POST",
      body: JSON.stringify({ code: mfaCode }),
    });
    setRecoveryCodes(result.recovery_codes);
    setMfaEnrollment(undefined);
    setMfaCode("");
    setMessage("双重验证已启用。请立即离线保存恢复码，每个只能使用一次。");
    await load();
  }

  async function stepUpMfa() {
    await api("/auth/mfa/step-up", { method: "POST", body: JSON.stringify({ code: mfaCode }) });
    setMfaCode("");
    setMessage("当前设备已完成管理员二次验证。");
    await load();
  }

  async function disableMfa() {
    if (!window.confirm("关闭双重验证会降低账号安全性。确定继续吗？")) return;
    await api("/auth/mfa", {
      method: "DELETE",
      body: JSON.stringify({ password: mfaPassword, code: mfaCode }),
    });
    setMfaPassword("");
    setMfaCode("");
    setRecoveryCodes([]);
    setMessage("双重验证已关闭。");
    await load();
  }

  return (
    <div className="page">
      <div className="pageHead">
        <div>
          <p className="eyebrow">PRIVACY & MODELS</p>
          <h1>模型与隐私</h1>
          <p>默认使用平台额度；也可以保存自己的模型密钥，并在创建游戏时选择 BYOK。</p>
        </div>
      </div>
      {message && (
        <p className="success" role="status">
          {message}
        </p>
      )}
      <div className="cardGrid">
        <section className="panel stack">
          <div>
            <p className="eyebrow">YOUR CHOICE</p>
            <h2>帮助改进游戏体验</h2>
            <p className="studioHint">
              默认关闭。开启后仅记录“开始游戏、完成回合、抵达结局、创建与发布作品”等服务器定义事件，用来发现流程卡点。
            </p>
          </div>
          <label className="consentToggle">
            <input
              type="checkbox"
              checked={privacy?.product_analytics ?? false}
              disabled={!privacy}
              onChange={(event) =>
                updateAnalytics(event.target.checked).catch((exception) =>
                  setMessage(exception.message),
                )
              }
            />
            <span>
              <b>允许匿名产品改进数据</b>
              <small>可随时撤回；撤回会立即删除此前事件。</small>
            </span>
          </label>
          <p className="studioHint">
            <b>永不记录：</b>
            {privacy?.collection.never.join("、") ?? "玩家输入、生成正文、邮箱、模型密钥、IP 地址"}
            。
          </p>
          {privacy?.consent_updated_at && (
            <small>最近选择：{new Date(privacy.consent_updated_at).toLocaleString("zh-CN")}</small>
          )}
        </section>

        <section className="panel">
          <h2>平台额度</h2>
          {usage ? (
            <>
              <UsageBar label="今日" used={usage.daily.used} limit={usage.daily.limit} />
              <UsageBar label="本月" used={usage.monthly.used} limit={usage.monthly.limit} />
              <p className="studioHint">
                单回合最多预留 {usage.turn_limit.toLocaleString()}{" "}
                tokens；达到限额后不会继续调用平台模型。
              </p>
            </>
          ) : (
            <p>正在读取额度…</p>
          )}
        </section>

        <form className="panel stack" onSubmit={save}>
          <h2>添加或轮换 BYOK 密钥</h2>
          <p className="studioHint">
            使用自己的密钥不会消耗平台额度。密钥只会加密保存，任何接口都不会回显完整内容。
          </p>
          <label className="field">
            <span>供应商</span>
            <select
              className="select"
              name="provider_preset"
              value={providerPreset}
              onChange={(event) => chooseProvider(event.target.value)}
            >
              <option value="compatible:deepseek">DeepSeek</option>
              <option value="compatible:volcengine">火山引擎方舟</option>
              <option value="compatible:custom">其他 OpenAI 兼容接口</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </label>
          {providerPreset.startsWith("compatible:") && (
            <label className="field">
              <span>API 基础地址</span>
              <input
                className="input"
                name="base_url"
                type="url"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://api.example.com/v1"
                required
              />
              <small>填写到版本路径即可，不要包含 /chat/completions。</small>
            </label>
          )}
          <label className="field">
            <span>模型名称</span>
            <input
              className="input"
              name="model"
              placeholder={
                providerPreset === "compatible:deepseek"
                  ? "例如 deepseek-chat"
                  : providerPreset === "compatible:volcengine"
                    ? "填写方舟推理接入点 ID"
                    : "由你的供应商提供"
              }
              required
            />
          </label>
          <label className="field">
            <span>API 密钥</span>
            <input
              className="input"
              name="secret"
              type="password"
              autoComplete="off"
              required
              minLength={8}
            />
          </label>
          <button className="button primary">加密保存</button>
        </form>

        <section className="panel">
          <h2>已保存密钥</h2>
          {keys.length ? (
            keys.map((key) => (
              <div className="credentialRow" key={key.provider}>
                <span>
                  <b>{key.provider === "compatible" ? "OpenAI 兼容接口" : key.provider}</b>
                  <small>
                    {key.model} · {key.hint}
                  </small>
                  {key.base_url && <small>{key.base_url}</small>}
                </span>
                <div>
                  <button
                    className="dangerLink"
                    onClick={() =>
                      testKey(key.provider).catch((exception) => setMessage(exception.message))
                    }
                  >
                    测试
                  </button>
                  <button
                    className="dangerLink"
                    onClick={() =>
                      remove(key.provider).catch((exception) => setMessage(exception.message))
                    }
                  >
                    删除
                  </button>
                </div>
              </div>
            ))
          ) : (
            <p className="studioHint">尚未保存自带密钥。</p>
          )}
        </section>

        <section className="panel">
          <h2>登录设备</h2>
          {sessions.map((session) => (
            <div className="credentialRow" key={session.id}>
              <span>
                <b>{session.current ? "当前设备" : session.ip_address}</b>
                <small>
                  {session.user_agent || "未知客户端"}
                  <br />
                  最近使用 {new Date(session.last_seen_at).toLocaleString()}
                </small>
              </span>
              <button
                className="dangerLink"
                onClick={() => revoke(session).catch((exception) => setMessage(exception.message))}
              >
                {session.current ? "退出" : "撤销"}
              </button>
            </div>
          ))}
        </section>

        <section className="panel stack mfaPanel">
          <div>
            <h2>双重验证</h2>
            <p className="studioHint">
              使用支持 TOTP 的验证器。管理员必须先完成本设备二次验证，才能进入管理与审核操作。
            </p>
          </div>
          {mfa?.required_for_admin && (
            <p className={mfa.enabled && mfa.step_up_valid ? "success" : "error"}>
              {mfa.enabled
                ? mfa.step_up_valid
                  ? "当前管理员会话已完成二次验证"
                  : "当前管理员会话需要再次验证"
                : "管理员账号必须启用双重验证"}
            </p>
          )}
          {!mfa?.enabled && !mfaEnrollment && (
            <>
              <label className="field">
                <span>确认当前密码</span>
                <input
                  className="input"
                  type="password"
                  value={mfaPassword}
                  onChange={(event) => setMfaPassword(event.target.value)}
                  autoComplete="current-password"
                />
              </label>
              <button
                className="button primary"
                disabled={!mfaPassword}
                onClick={() => startMfa().catch((exception) => setMessage(exception.message))}
              >
                开始绑定验证器
              </button>
            </>
          )}
          {mfaEnrollment && (
            <div className="mfaEnrollment">
              <span>验证器设置密钥</span>
              <code>{mfaEnrollment.secret}</code>
              <details>
                <summary>显示完整 otpauth 地址</summary>
                <code>{mfaEnrollment.otpauth_uri}</code>
              </details>
            </div>
          )}
          {(mfa?.enabled || mfaEnrollment) && (
            <label className="field">
              <span>六位验证码或恢复码</span>
              <input
                className="input"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={mfaCode}
                onChange={(event) => setMfaCode(event.target.value)}
                placeholder="123456"
              />
            </label>
          )}
          {mfaEnrollment && (
            <button
              className="button primary"
              disabled={!mfaCode}
              onClick={() => confirmMfa().catch((exception) => setMessage(exception.message))}
            >
              确认并生成恢复码
            </button>
          )}
          {mfa?.enabled && !mfa.step_up_valid && (
            <button
              className="button primary"
              disabled={!mfaCode}
              onClick={() => stepUpMfa().catch((exception) => setMessage(exception.message))}
            >
              验证当前设备
            </button>
          )}
          {mfa?.enabled && (
            <>
              <p className="studioHint">剩余恢复码：{mfa.recovery_codes_remaining}</p>
              <label className="field">
                <span>关闭时再次确认密码</span>
                <input
                  className="input"
                  type="password"
                  value={mfaPassword}
                  onChange={(event) => setMfaPassword(event.target.value)}
                  autoComplete="current-password"
                />
              </label>
              <button
                className="dangerLink"
                disabled={!mfaPassword || !mfaCode}
                onClick={() => disableMfa().catch((exception) => setMessage(exception.message))}
              >
                关闭双重验证
              </button>
            </>
          )}
          {recoveryCodes.length > 0 && (
            <div className="recoveryCodes" role="status">
              <b>一次性恢复码</b>
              {recoveryCodes.map((code) => (
                <code key={code}>{code}</code>
              ))}
            </div>
          )}
        </section>

        <section className="panel stack">
          <h2>你的数据</h2>
          <p className="studioHint">导出账号、作品、版本与游戏记录索引；完整删除有 30 天反悔期。</p>
          <button
            className="button primary"
            onClick={() => exportData().catch((exception) => setMessage(exception.message))}
          >
            下载个人数据
          </button>
          <button
            className="dangerLink"
            onClick={() => deleteAccount().catch((exception) => setMessage(exception.message))}
          >
            注销账号
          </button>
        </section>
      </div>
    </div>
  );
}

function UsageBar({ label, used, limit }: { label: string; used: number; limit: number }) {
  const percent = Math.min(100, Math.round((used / Math.max(limit, 1)) * 100));
  return (
    <div className="usageBlock">
      <div>
        <span>{label}</span>
        <b>
          {used.toLocaleString()} / {limit.toLocaleString()}
        </b>
      </div>
      <progress value={used} max={Math.max(limit, 1)} />
      <small>{percent}%</small>
    </div>
  );
}
