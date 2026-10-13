import { Check, RotateCcw, X } from "lucide-react";
import type { CaseResult } from "./case-types";

function Mark({ ok, label }: { ok: boolean; label: string }) {
  return (
    <li className={ok ? "ok" : "miss"}>
      {ok ? <Check size={15} aria-hidden="true" /> : <X size={15} aria-hidden="true" />}
      {label}
    </li>
  );
}

/** The ending, and an honest account of what held up and what did not. */
export function Verdict({
  result,
  busy,
  onRestart,
}: {
  result: CaseResult;
  busy: boolean;
  onRestart: () => void;
}) {
  return (
    <section className={`caseVerdict ${result.solved ? "solved" : ""}`} aria-label="结案">
      <p className="caseStamp big">{result.solved ? "结案" : "未结"}</p>
      <h2>{result.title}</h2>
      {result.text.split(/\n\s*\n/).map((paragraph) => (
        <p key={paragraph.slice(0, 24)}>{paragraph.trim()}</p>
      ))}
      {result.epilogues.map((line) => (
        <p className="caseEpilogue" key={line}>
          {line}
        </p>
      ))}
      <ul className="caseScore">
        <Mark ok={result.culprit_correct} label={`指认：${result.accused}`} />
        <Mark ok={result.weapon_correct} label="凶器" />
        <Mark ok={result.motive_correct} label="动机" />
        {result.pillars.map((pillar) => (
          <Mark key={pillar.key} ok={pillar.met} label={pillar.label} />
        ))}
      </ul>
      <p className="caseHint">
        戳穿谎言 {result.lies_broken}/{result.lies_total} · 找到证据 {result.evidence_found}/
        {result.evidence_total} · 剩余 {result.minutes_left} 分钟
      </p>
      <button className="button primary" onClick={onRestart} disabled={busy}>
        <RotateCcw size={16} aria-hidden="true" /> 重新调查这件案子
      </button>
    </section>
  );
}
