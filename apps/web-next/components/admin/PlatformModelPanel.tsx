"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";

type PlatformModelConfig = {
  enabled: boolean;
  provider: "openai" | "anthropic" | "compatible";
  model: string;
  base_url: string;
  extra_body: Record<string, unknown>;
  narrative_model: string;
  narrative_extra_body: Record<string, unknown>;
  reasoning_enabled: boolean;
  reasoning_model: string;
  reasoning_extra_body: Record<string, unknown>;
  role_assignments?: { narrative: string[]; reasoning: string[] };
  key_configured: boolean;
  key_hint: string;
  source: "environment" | "database";
  updated_at?: string | null;
};

type TestResult = {
  profile: "narrative" | "reasoning";
  provider: string;
  model: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
};

type BusyAction = "" | "save" | "narrative" | "reasoning";

const EMPTY: PlatformModelConfig = {
  enabled: true,
  provider: "compatible",
  model: "",
  base_url: "",
  extra_body: {},
  narrative_model: "",
  narrative_extra_body: {},
  reasoning_enabled: false,
  reasoning_model: "",
  reasoning_extra_body: {},
  key_configured: false,
  key_hint: "",
  source: "environment",
};

function messageOf(exception: unknown): string {
  return exception instanceof Error ? exception.message : "请求没有完成";
}

function parseJsonObject(value: string, label: string): Record<string, unknown> {
  const parsed = JSON.parse(value || "{}") as unknown;
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label}必须是 JSON 对象。`);
  }
  return parsed as Record<string, unknown>;
}

function thinkingEnabled(value: string): boolean {
  try {
    const parsed = JSON.parse(value) as { thinking?: { type?: string } };
    return parsed.thinking?.type === "enabled";
  } catch {
    return false;
  }
}

export default function PlatformModelPanel() {
  const [config, setConfig] = useState<PlatformModelConfig>(EMPTY);
  const [apiKey, setApiKey] = useState("");
  const [narrativeExtraBody, setNarrativeExtraBody] = useState("{}");
  const [reasoningExtraBody, setReasoningExtraBody] = useState("{}");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<BusyAction>("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  function apply(next: PlatformModelConfig) {
    const normalized = {
      ...next,
      narrative_model: next.narrative_model || next.model,
      narrative_extra_body: next.narrative_extra_body ?? next.extra_body ?? {},
      reasoning_model: next.reasoning_model || next.narrative_model || next.model,
      reasoning_extra_body:
        next.reasoning_extra_body ?? next.narrative_extra_body ?? next.extra_body ?? {},
    };
    setConfig(normalized);
    setNarrativeExtraBody(JSON.stringify(normalized.narrative_extra_body, null, 2));
    setReasoningExtraBody(JSON.stringify(normalized.reasoning_extra_body, null, 2));
  }

  useEffect(() => {
    api<PlatformModelConfig>("/admin/llm-config")
      .then(apply)
      .catch((exception) => setError(messageOf(exception)));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy("save");
    setError("");
    setMessage("");
    try {
      const narrativeBody = parseJsonObject(narrativeExtraBody, "叙事模型附加请求参数");
      const reasoningBody = parseJsonObject(reasoningExtraBody, "推理模型附加请求参数");
      const next = await api<PlatformModelConfig>("/admin/llm-config", {
        method: "PUT",
        body: JSON.stringify({
          enabled: config.enabled,
          provider: config.provider,
          base_url: config.base_url,
          api_key: apiKey || undefined,
          narrative_model: config.narrative_model,
          narrative_extra_body: narrativeBody,
          reasoning_enabled: config.reasoning_enabled,
          reasoning_model: config.reasoning_model,
          reasoning_extra_body: reasoningBody,
          reason,
        }),
      });
      apply(next);
      setApiKey("");
      setReason("");
      setMessage("模型路由已保存，并会从下一次游戏请求开始生效。");
    } catch (exception) {
      setError(messageOf(exception));
    } finally {
      setBusy("");
    }
  }

  async function testConnection(profile: "narrative" | "reasoning") {
    setBusy(profile);
    setError("");
    setMessage("");
    try {
      const result = await api<TestResult>(`/admin/llm-config/test?profile=${profile}`, {
        method: "POST",
      });
      const label = profile === "narrative" ? "叙事模型" : "推理模型";
      setMessage(
        `${label}连接成功：${result.model} · ${result.latency_ms} ms · ${result.input_tokens + result.output_tokens} tokens。此结果验证网络、密钥和模型名称，不代表完整游戏回合的质量与延迟。`,
      );
    } catch (exception) {
      setError(messageOf(exception));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="panel stack" aria-labelledby="platform-model-title">
      <div className="entityToolbar">
        <div>
          <h2 id="platform-model-title">平台模型路由</h2>
          <p>一套加密连接，两种职责。叙事负责玩家可见文本，推理负责结构化决策。</p>
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
          <span>API 基础地址</span>
          <input
            className="input"
            type="url"
            value={config.base_url}
            placeholder="https://api.deepseek.com"
            onChange={(event) => setConfig({ ...config, base_url: event.target.value })}
          />
        </label>
        <label className="modelConnectionKey">
          <span>共享 API 密钥</span>
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
        <p className="modelConnectionNote">
          两个档案默认共用上面的供应商、地址与密钥，但请求参数、模型名称和输出预算按职责隔离。
        </p>

        <div className="modelProfiles">
          <article className="modelProfileCard">
            <div className="modelProfileHeader">
              <div>
                <small>玩家可见文本</small>
                <h3>叙事模型</h3>
              </div>
              <span>长文本 · 高文采 · 流式输出</span>
            </div>
            <p>负责开场、章节正文和场景描写。建议关闭深度思考，把输出预算留给正文。</p>
            <label>
              <span>叙事模型名称</span>
              <input
                className="input"
                required
                value={config.narrative_model}
                placeholder="deepseek-chat"
                onChange={(event) => setConfig({ ...config, narrative_model: event.target.value })}
              />
            </label>
            <label className="modelJsonField">
              <span>叙事附加请求参数（JSON）</span>
              <textarea
                className="textarea"
                rows={5}
                value={narrativeExtraBody}
                spellCheck={false}
                onChange={(event) => setNarrativeExtraBody(event.target.value)}
              />
              <small>例如关闭思考模式：{`{"thinking":{"type":"disabled"}}`}</small>
              {thinkingEnabled(narrativeExtraBody) && (
                <small className="modelWarning">
                  叙事档案已启用思考模式，隐藏推理可能消耗正文 Token 并增加首字等待时间。
                </small>
              )}
            </label>
            <button
              className="button"
              type="button"
              disabled={Boolean(busy)}
              onClick={() => testConnection("narrative")}
            >
              {busy === "narrative" ? "测试中…" : "测试已保存的叙事模型"}
            </button>
          </article>

          <article className="modelProfileCard modelProfileReasoning">
            <div className="modelProfileHeader">
              <div>
                <small>后台结构化决策</small>
                <h3>推理模型</h3>
              </div>
              <span>导演 · NPC · 世界维护</span>
            </div>
            <p>负责意图识别、导演、NPC、世界维护和记忆提取，优先保证 JSON 与逻辑稳定。</p>
            <label className="modelToggle">
              <input
                type="checkbox"
                checked={config.reasoning_enabled}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    reasoning_enabled: event.target.checked,
                    reasoning_model: config.reasoning_model || config.narrative_model,
                  })
                }
              />
              使用独立推理模型
            </label>
            <label>
              <span>推理模型名称</span>
              <input
                className="input"
                required={config.reasoning_enabled}
                disabled={!config.reasoning_enabled}
                value={config.reasoning_model}
                placeholder={config.narrative_model || "与叙事模型相同"}
                onChange={(event) => setConfig({ ...config, reasoning_model: event.target.value })}
              />
            </label>
            <label className="modelJsonField">
              <span>推理附加请求参数（JSON）</span>
              <textarea
                className="textarea"
                rows={5}
                disabled={!config.reasoning_enabled}
                value={reasoningExtraBody}
                spellCheck={false}
                onChange={(event) => setReasoningExtraBody(event.target.value)}
              />
              <small>未启用独立档案时自动继承叙事配置；启用后可单独打开思考模式。</small>
            </label>
            <button
              className="button"
              type="button"
              disabled={Boolean(busy)}
              onClick={() => testConnection("reasoning")}
            >
              {busy === "reasoning" ? "测试中…" : "测试已保存的推理模型"}
            </button>
          </article>
        </div>

        <div className="modelRoleList" aria-label="模型职责路由">
          <span>叙事：开场、章节、场景正文</span>
          <span>推理：意图、NPC、导演、世界维护、记忆</span>
          <span>失败时：确定性规则降级</span>
        </div>
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
          <button className="button primary" disabled={Boolean(busy)}>
            {busy === "save" ? "保存中…" : "保存模型路由"}
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
