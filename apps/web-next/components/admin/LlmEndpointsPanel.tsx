"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

type Endpoint = {
  id: string;
  name: string;
  enabled: boolean;
  priority: number;
  provider: string;
  base_url: string;
  narrative_model: string;
  reasoning_model: string;
  narrative_extra_body: Record<string, unknown>;
  reasoning_extra_body: Record<string, unknown>;
  key_configured: boolean;
  key_hint: string;
  last_ok_at?: string | null;
  last_error_at?: string | null;
  last_error: string;
  consecutive_failures: number;
};

type Listing = { items: Endpoint[]; supported_providers: string[]; max_endpoints: number };
type Stage = { stage: "narrative" | "reasoning"; ok: boolean; detail: string };
type TestResult = { ok: boolean; stages: Stage[]; endpoint: Endpoint };

type Draft = {
  name: string;
  provider: string;
  base_url: string;
  narrative_model: string;
  reasoning_model: string;
  api_key: string;
  enabled: boolean;
  narrative_extra_body: string;
  reasoning_extra_body: string;
};

const EMPTY_DRAFT: Draft = {
  name: "",
  provider: "compatible",
  base_url: "",
  narrative_model: "",
  reasoning_model: "",
  api_key: "",
  enabled: true,
  narrative_extra_body: "{}",
  reasoning_extra_body: "{}",
};

function parseJsonObject(value: string, label: string): Record<string, unknown> {
  const parsed = JSON.parse(value || "{}") as unknown;
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label}必须是 JSON 对象。`);
  }
  return parsed as Record<string, unknown>;
}

const stageLabel = { narrative: "叙事（流式）", reasoning: "推理（结构化）" } as const;

function messageOf(exception: unknown): string {
  return exception instanceof Error ? exception.message : "请求没有完成";
}

function health(endpoint: Endpoint): { tone: "ok" | "bad" | "unknown"; text: string } {
  if (endpoint.consecutive_failures > 0)
    return {
      tone: "bad",
      text: `连续失败 ${endpoint.consecutive_failures} 次：${endpoint.last_error || "未知原因"}`,
    };
  if (endpoint.last_ok_at) return { tone: "ok", text: "上次预检通过" };
  return { tone: "unknown", text: "尚未预检" };
}

export default function LlmEndpointsPanel() {
  const [listing, setListing] = useState<Listing>();
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [editing, setEditing] = useState<string>("");
  const [busy, setBusy] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [results, setResults] = useState<Record<string, TestResult>>({});

  const load = useCallback(async () => {
    try {
      setListing(await api<Listing>("/admin/llm-endpoints"));
    } catch (exception) {
      setError(messageOf(exception));
    }
  }, []);

  useEffect(() => {
    api<Listing>("/admin/llm-endpoints")
      .then(setListing)
      .catch((exception) => setError(messageOf(exception)));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy("save");
    setError("");
    try {
      const body: Record<string, unknown> = {
        name: draft.name,
        enabled: draft.enabled,
        provider: draft.provider,
        base_url: draft.base_url,
        narrative_model: draft.narrative_model,
        reasoning_model: draft.reasoning_model,
        narrative_extra_body: parseJsonObject(draft.narrative_extra_body, "叙事附加参数"),
        reasoning_extra_body: parseJsonObject(draft.reasoning_extra_body, "推理附加参数"),
        priority: editing
          ? (listing?.items.find((item) => item.id === editing)?.priority ?? 100)
          : (listing?.items.length ?? 0),
      };
      // An empty box means "keep the stored key", never "erase it".
      if (draft.api_key) body.api_key = draft.api_key;
      if (editing) {
        await api(`/admin/llm-endpoints/${editing}`, { method: "PUT", body: JSON.stringify(body) });
        setStatus("端点已更新");
      } else {
        await api("/admin/llm-endpoints", { method: "POST", body: JSON.stringify(body) });
        setStatus("端点已添加");
      }
      setDraft(EMPTY_DRAFT);
      setEditing("");
      await load();
    } catch (exception) {
      setError(messageOf(exception));
    } finally {
      setBusy("");
    }
  }

  async function runTest(id: string) {
    setBusy(id);
    setError("");
    setStatus("正在按真实游玩方式预检：流式叙事 + 结构化推理…");
    try {
      const result = await api<TestResult>(`/admin/llm-endpoints/${id}/test`, { method: "POST" });
      setResults((current) => ({ ...current, [id]: result }));
      setStatus(result.ok ? "预检通过，这个端点可以承担真实回合" : "预检未通过");
      await load();
    } catch (exception) {
      setError(messageOf(exception));
      setStatus("");
    } finally {
      setBusy("");
    }
  }

  async function remove(id: string) {
    setBusy(id);
    setError("");
    try {
      await api(`/admin/llm-endpoints/${id}`, { method: "DELETE" });
      setStatus("端点已删除");
      await load();
    } catch (exception) {
      setError(messageOf(exception));
    } finally {
      setBusy("");
    }
  }

  async function move(id: string, direction: -1 | 1) {
    if (!listing) return;
    const order = listing.items.map((item) => item.id);
    const index = order.indexOf(id);
    const next = index + direction;
    if (index < 0 || next < 0 || next >= order.length) return;
    [order[index], order[next]] = [order[next], order[index]];
    setBusy(id);
    try {
      await api("/admin/llm-endpoints/reorder", {
        method: "POST",
        body: JSON.stringify({ order }),
      });
      setStatus("已调整优先级");
      await load();
    } catch (exception) {
      setError(messageOf(exception));
    } finally {
      setBusy("");
    }
  }

  function edit(endpoint: Endpoint) {
    setEditing(endpoint.id);
    setDraft({
      name: endpoint.name,
      provider: endpoint.provider,
      base_url: endpoint.base_url,
      narrative_model: endpoint.narrative_model,
      reasoning_model: endpoint.reasoning_model,
      api_key: "",
      enabled: endpoint.enabled,
      narrative_extra_body: JSON.stringify(endpoint.narrative_extra_body ?? {}, null, 2),
      reasoning_extra_body: JSON.stringify(endpoint.reasoning_extra_body ?? {}, null, 2),
    });
  }

  const items = listing?.items ?? [];
  const full = listing ? items.length >= listing.max_endpoints : false;

  return (
    <section className="panel stack">
      <div className="entityToolbar">
        <h2>模型端点</h2>
        <p>
          按顺序依次尝试：排在前面的端点失败时，下一个会立刻接手，玩家不会看到中断。
          每个端点有各自的密钥与模型名称，可以是不同厂商。
        </p>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {status && !error && <p className="modelConnectionNote">{status}</p>}

      <ol className="endpointList">
        {items.length === 0 && (
          <li className="empty">还没有配置任何端点，平台当前无法生成内容。</li>
        )}
        {items.map((endpoint, index) => {
          const state = health(endpoint);
          const result = results[endpoint.id];
          return (
            <li key={endpoint.id} className={endpoint.enabled ? "" : "disabled"}>
              <div className="endpointHead">
                <span className="endpointRank">{index + 1}</span>
                <div>
                  <strong>
                    {endpoint.name}
                    {!endpoint.enabled && <em> · 已停用</em>}
                  </strong>
                  <small>
                    {endpoint.provider} · {endpoint.base_url || "（默认地址）"} ·{" "}
                    {endpoint.key_configured ? `密钥 ${endpoint.key_hint}` : "未配置密钥"}
                  </small>
                  <small>
                    叙事 {endpoint.narrative_model || "—"} · 推理{" "}
                    {endpoint.reasoning_model || endpoint.narrative_model || "—"}
                  </small>
                  <small className={`endpointHealth ${state.tone}`}>{state.text}</small>
                </div>
                <div className="endpointActions">
                  <button
                    className="button"
                    disabled={busy !== "" || index === 0}
                    onClick={() => move(endpoint.id, -1)}
                    aria-label={`把 ${endpoint.name} 上移`}
                  >
                    ↑
                  </button>
                  <button
                    className="button"
                    disabled={busy !== "" || index === items.length - 1}
                    onClick={() => move(endpoint.id, 1)}
                    aria-label={`把 ${endpoint.name} 下移`}
                  >
                    ↓
                  </button>
                  <button
                    className="button"
                    disabled={busy !== ""}
                    onClick={() => runTest(endpoint.id)}
                  >
                    {busy === endpoint.id ? "预检中…" : "预检"}
                  </button>
                  <button className="button" disabled={busy !== ""} onClick={() => edit(endpoint)}>
                    编辑
                  </button>
                  <button
                    className="button"
                    disabled={busy !== ""}
                    onClick={() => remove(endpoint.id)}
                  >
                    删除
                  </button>
                </div>
              </div>
              {result && (
                <ul className="endpointStages">
                  {result.stages.map((stage) => (
                    <li key={stage.stage} className={stage.ok ? "ok" : "bad"}>
                      <strong>{stageLabel[stage.stage]}</strong>
                      <span>{stage.detail}</span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>

      <form className="modelConfigForm" onSubmit={submit}>
        <h4>{editing ? "编辑端点" : "添加端点"}</h4>
        <label className="modelReasonField">
          <span>名称</span>
          <input
            className="input"
            value={draft.name}
            required
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          />
        </label>
        <label className="modelReasonField">
          <span>厂商</span>
          <select
            className="select"
            value={draft.provider}
            onChange={(event) => setDraft({ ...draft, provider: event.target.value })}
          >
            {(listing?.supported_providers ?? ["compatible"]).map((provider) => (
              <option key={provider} value={provider}>
                {provider}
              </option>
            ))}
          </select>
        </label>
        <label className="modelReasonField">
          <span>API Base URL</span>
          <input
            className="input"
            value={draft.base_url}
            placeholder="https://example.com/v1"
            onChange={(event) => setDraft({ ...draft, base_url: event.target.value })}
          />
          <small>
            请求会在这个地址后面直接拼 /chat/completions，所以通常要填到 /v1 为止。
          </small>
        </label>
        <label className="modelReasonField">
          <span>叙事模型</span>
          <input
            className="input"
            value={draft.narrative_model}
            required
            onChange={(event) => setDraft({ ...draft, narrative_model: event.target.value })}
          />
          <small>负责玩家看到的正文，需要支持流式输出。</small>
        </label>
        <label className="modelReasonField">
          <span>推理模型</span>
          <input
            className="input"
            value={draft.reasoning_model}
            placeholder="留空则与叙事模型相同"
            onChange={(event) => setDraft({ ...draft, reasoning_model: event.target.value })}
          />
          <small>负责意图、导演、NPC、记忆等结构化环节，需要支持 JSON 输出。</small>
        </label>
        <label className="modelJsonField">
          <span>叙事附加参数（JSON）</span>
          <textarea
            className="input"
            rows={3}
            value={draft.narrative_extra_body}
            onChange={(event) =>
              setDraft({ ...draft, narrative_extra_body: event.target.value })
            }
          />
          <small>原样并入请求体，用于厂商专有开关。</small>
        </label>
        <label className="modelJsonField">
          <span>推理附加参数（JSON）</span>
          <textarea
            className="input"
            rows={3}
            value={draft.reasoning_extra_body}
            onChange={(event) =>
              setDraft({ ...draft, reasoning_extra_body: event.target.value })
            }
          />
        </label>
        <label className="modelReasonField">
          <span>API Key</span>
          <input
            className="input"
            type="password"
            value={draft.api_key}
            placeholder={editing ? "留空表示不修改已保存的密钥" : ""}
            onChange={(event) => setDraft({ ...draft, api_key: event.target.value })}
          />
        </label>
        <label className="modelToggle">
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
          />
          <span>启用</span>
        </label>
        <div className="modelActions">
          <button className="button primary" disabled={busy === "save" || (!editing && full)}>
            {busy === "save" ? "保存中…" : editing ? "保存修改" : "添加端点"}
          </button>
          {editing && (
            <button
              type="button"
              className="button"
              onClick={() => {
                setEditing("");
                setDraft(EMPTY_DRAFT);
              }}
            >
              取消
            </button>
          )}
          {!editing && full && <small>已达到 {listing?.max_endpoints} 个端点上限。</small>}
        </div>
      </form>
    </section>
  );
}
