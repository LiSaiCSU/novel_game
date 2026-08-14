"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";

type PlatformModelConfig = {
  enabled: boolean;
  provider: "openai" | "anthropic" | "compatible";
  model: string;
  base_url: string;
  extra_body: Record<string, unknown>;
  key_configured: boolean;
  key_hint: string;
  source: "environment" | "database";
  updated_at?: string | null;
};

type TestResult = {
  provider: string;
  model: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
};

const EMPTY: PlatformModelConfig = {
  enabled: true,
  provider: "compatible",
  model: "",
  base_url: "",
  extra_body: {},
  key_configured: false,
  key_hint: "",
  source: "environment",
};

function messageOf(exception: unknown): string {
  return exception instanceof Error ? exception.message : "请求没有完成";
}

export default function PlatformModelPanel() {
  const [config, setConfig] = useState<PlatformModelConfig>(EMPTY);
  const [apiKey, setApiKey] = useState("");
  const [extraBody, setExtraBody] = useState("{}");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  function apply(next: PlatformModelConfig) {
    setConfig(next);
    setExtraBody(JSON.stringify(next.extra_body ?? {}, null, 2));
  }

  useEffect(() => {
    api<PlatformModelConfig>("/admin/llm-config")
      .then(apply)
      .catch((exception) => setError(messageOf(exception)));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const parsed = JSON.parse(extraBody || "{}");
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("附加请求参数必须是 JSON 对象。");
      }
      const next = await api<PlatformModelConfig>("/admin/llm-config", {
        method: "PUT",
        body: JSON.stringify({
          enabled: config.enabled,
          provider: config.provider,
          model: config.model,
          base_url: config.base_url,
          api_key: apiKey || undefined,
          extra_body: parsed,
          reason,
        }),
      });
      apply(next);
      setApiKey("");
      setReason("");
      setMessage("平台模型配置已保存，并会从下一次游戏请求开始生效。");
    } catch (exception) {
      setError(messageOf(exception));
    } finally {
      setBusy(false);
    }
  }

  async function testConnection() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api<TestResult>("/admin/llm-config/test", { method: "POST" });
      setMessage(
        `连接成功：${result.model} · ${result.latency_ms} ms · ${result.input_tokens + result.output_tokens} tokens`,
      );
    } catch (exception) {
      setError(messageOf(exception));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel stack" aria-labelledby="platform-model-title">
      <div className="entityToolbar">
        <div>
          <h2 id="platform-model-title">平台叙事模型</h2>
          <p>玩家选择“平台额度”时使用。密钥只写入加密存储，页面和接口都不会回显。</p>
        </div>
        <span className={config.enabled ? "modelStatus modelStatusOn" : "modelStatus"}>
          {config.enabled ? "已启用" : "已停用"}
        </span>
      </div>

      <form className="modelConfigForm" onSubmit={save}>
        <label className="modelToggle">
          <input
            type="checkbox"
            checked={config.enabled}
            onChange={(event) => setConfig({ ...config, enabled: event.target.checked })}
          />
          允许玩家使用平台模型额度
        </label>
        <label>
          <span>接口类型</span>
          <select
            className="select"
            value={config.provider}
            onChange={(event) =>
              setConfig({
                ...config,
                provider: event.target.value as PlatformModelConfig["provider"],
              })
            }
          >
            <option value="compatible">OpenAI 兼容（DeepSeek / 火山等）</option>
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </label>
        <label>
          <span>API Base URL</span>
          <input
            className="input"
            type="url"
            value={config.base_url}
            placeholder="https://api.deepseek.com"
            onChange={(event) => setConfig({ ...config, base_url: event.target.value })}
          />
        </label>
        <label>
          <span>模型名称</span>
          <input
            className="input"
            required
            value={config.model}
            placeholder="deepseek-chat"
            onChange={(event) => setConfig({ ...config, model: event.target.value })}
          />
        </label>
        <label>
          <span>API 密钥</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            value={apiKey}
            placeholder={
              config.key_configured ? `${config.key_hint || "已配置"}（留空不变）` : "请输入密钥"
            }
            onChange={(event) => setApiKey(event.target.value)}
          />
        </label>
        <label className="modelJsonField">
          <span>附加请求参数（JSON）</span>
          <textarea
            className="textarea"
            rows={4}
            value={extraBody}
            spellCheck={false}
            onChange={(event) => setExtraBody(event.target.value)}
          />
          <small>例如 DeepSeek 关闭思考模式：{`{"thinking":{"type":"disabled"}}`}</small>
        </label>
        <label className="modelReasonField">
          <span>变更理由（写入审计日志）</span>
          <input
            className="input"
            required
            minLength={3}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        <div className="modelActions">
          <button className="button primary" disabled={busy}>
            {busy ? "处理中…" : "保存配置"}
          </button>
          <button className="button" type="button" disabled={busy} onClick={testConnection}>
            测试当前配置
          </button>
          <small>当前来源：{config.source === "database" ? "管理界面" : "服务器环境变量"}</small>
        </div>
      </form>
      {message && (
        <p className="successNotice" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
