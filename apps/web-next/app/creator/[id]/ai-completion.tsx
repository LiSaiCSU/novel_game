"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Diagnostic, Package } from "./editor-types";

type CompletionResult = {
  document: Package;
  added: Record<string, number>;
  filled: string[];
  diagnostics: Diagnostic[];
};

const sectionLabels: Record<string, string> = {
  endings: "结局",
  facts: "事实与秘密",
  quests: "任务",
  characters: "人物目标与秘密",
  threads: "剧情线",
};

function describeAdded(added: Record<string, number>): string[] {
  return Object.entries(added)
    .filter(([, count]) => count > 0)
    .map(([section, count]) => `${sectionLabels[section] ?? section} ${count} 项`);
}

export function AiCompletion({
  projectId,
  onApply,
  onStatus,
}: {
  projectId: string;
  onApply: (document: Package) => void;
  onStatus: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CompletionResult>();
  const [error, setError] = useState("");

  async function run() {
    setBusy(true);
    setError("");
    onStatus("AI 正在补全草稿里还空着的部分…");
    try {
      // A fresh key each attempt: a retry after a failure is a new request,
      // not a replay of one that already consumed the writer's credits.
      const key = `complete-${projectId}-${Date.now()}`;
      const completion = await api<CompletionResult>(
        `/creator/projects/${projectId}/ai-complete`,
        { method: "POST", body: JSON.stringify({ idempotency_key: key, model_mode: "platform" }) },
      );
      setResult(completion);
      onStatus("补全结果已生成，确认后才会写入草稿");
    } catch (exception) {
      setError((exception as Error).message);
      onStatus("AI 补全没有改动你的草稿");
    } finally {
      setBusy(false);
    }
  }

  function apply() {
    if (!result) return;
    onApply(result.document);
    setResult(undefined);
  }

  const summary = result ? describeAdded(result.added) : [];
  return (
    <section className="aiCompletion">
      <header>
        <div>
          <strong>
            <Sparkles size={15} /> AI 补全剩余内容
          </strong>
          <p>
            只填还空着的部分——结局、事实、任务、人物目标。你已经写过的内容不会被改动，
            补全结果需要你确认后才会写入。
          </p>
        </div>
        <button className="button" onClick={run} disabled={busy}>
          {busy ? "正在补全…" : "开始补全"}
        </button>
      </header>

      {error && <p className="aiCompletionError">{error}</p>}

      {result && (
        <div className="aiCompletionResult">
          <p>
            本次补全了 {summary.length > 0 ? summary.join("、") : "0 项"}
            {result.diagnostics.length > 0 && `，另有 ${result.diagnostics.length} 条待处理提示`}。
          </p>
          <ul>
            {(result.document.content.endings ?? []).map((ending) => (
              <li key={ending.key}>
                <strong>{ending.title}</strong>
                <span>{String(ending.epilogue ?? "").slice(0, 60)}…</span>
              </li>
            ))}
          </ul>
          <div className="aiCompletionActions">
            <button className="button primary" onClick={apply}>
              写入草稿
            </button>
            <button className="button" onClick={() => setResult(undefined)}>
              丢弃
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
