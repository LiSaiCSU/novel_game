import { Check, Lock, RotateCcw, Star, X } from "lucide-react";
import type { CaseResult, RouteCard } from "./case-types";

function Mark({ ok, label }: { ok: boolean; label: string }) {
  return (
    <li className={ok ? "ok" : "miss"}>
      {ok ? <Check size={15} aria-hidden="true" /> : <X size={15} aria-hidden="true" />}
      {label}
    </li>
  );
}

function Paragraphs({ text }: { text: string }) {
  return (
    <>
      {text.split(/\n\s*\n/).map((paragraph) => (
        <p key={paragraph.slice(0, 24)}>{paragraph.trim()}</p>
      ))}
    </>
  );
}

/** The ending, and an honest account of what held up and what did not. */
export function Verdict({
  result,
  routes,
  busy,
  onRestart,
}: {
  result: CaseResult;
  routes: RouteCard[];
  busy: boolean;
  onRestart: () => void;
}) {
  if (result.mode === "scheme") {
    const found = routes.filter((route) => route.discovered).length;
    return (
      <section className={`caseVerdict ${result.solved ? "solved" : ""}`} aria-label="结局">
        <div className="caseGradeRow">
          <p className={`caseGrade grade-${result.grade}`} aria-label={`评级 ${result.grade}`}>
            {result.grade}
          </p>
          <div>
            <p className="eyebrow">{result.solved ? result.label : "失败"}</p>
            <h2>{result.title}</h2>
          </div>
        </div>
        <Paragraphs text={result.text} />
        {result.epilogues.map((line) => (
          <p className="caseEpilogue" key={line}>
            {line}
          </p>
        ))}
        {result.solved && !!result.stars?.length && (
          <ul className="caseStars" aria-label="加分目标">
            {result.stars.map((star) => (
              <li key={star.key} className={star.met ? "ok" : "miss"}>
                <Star size={15} aria-hidden="true" fill={star.met ? "currentColor" : "none"} />
                {star.label}
              </li>
            ))}
          </ul>
        )}
        <section className="caseRoutes" aria-label="解法收集">
          <h3>
            解法 {found}/{routes.length}
          </h3>
          <ul>
            {routes.map((route, index) => (
              <li key={route.key ?? `hidden-${index}`} className={route.discovered ? "found" : ""}>
                {route.discovered ? (
                  <>
                    <Check size={14} aria-hidden="true" />
                    <b>{route.title}</b>
                    <small>{route.label}</small>
                  </>
                ) : (
                  <>
                    <Lock size={14} aria-hidden="true" />
                    <span>{route.teaser}</span>
                  </>
                )}
              </li>
            ))}
          </ul>
        </section>
        <button className="button primary" onClick={onRestart} disabled={busy}>
          <RotateCcw size={16} aria-hidden="true" />
          {found < routes.length ? "换一种赢法" : "再来一局"}
        </button>
      </section>
    );
  }

  return (
    <section className={`caseVerdict ${result.solved ? "solved" : ""}`} aria-label="结案">
      <p className="caseStamp big">{result.solved ? "结案" : "未结"}</p>
      <h2>{result.title}</h2>
      <Paragraphs text={result.text} />
      {result.epilogues.map((line) => (
        <p className="caseEpilogue" key={line}>
          {line}
        </p>
      ))}
      <ul className="caseScore">
        <Mark ok={!!result.culprit_correct} label={`指认：${result.accused ?? ""}`} />
        <Mark ok={!!result.weapon_correct} label="凶器" />
        <Mark ok={!!result.motive_correct} label="动机" />
        {(result.pillars ?? []).map((pillar) => (
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
