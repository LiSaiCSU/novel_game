"use client";

import { BookOpen, FolderOpen, Gavel, Lightbulb, MessageSquareText, Users } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorState, LoadingState, RetryButton } from "@/components/ui/async-state";
import { api } from "@/lib/api";
import { Accusation } from "./accusation";
import { Briefing } from "./briefing";
import { CaseDock, Patience } from "./case-dock";
import { CaseLog } from "./case-log";
import type { CaseCharacter, CaseRun, MoveBody } from "./case-types";
import { EvidenceFolder, EvidencePicker } from "./evidence";
import { useCaseRun } from "./use-case-run";
import { Verdict } from "./verdict";
import "../case.css";

type MobileView = "investigate" | "people" | "evidence";

export default function CasePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const game = useCaseRun(id);
  const [briefingOpen, setBriefingOpen] = useState(false);
  const [accusing, setAccusing] = useState(false);
  const [challenge, setChallenge] = useState<{ character: CaseCharacter; statement: string }>();
  const [focus, setFocus] = useState("");
  const [view, setView] = useState<MobileView>("investigate");
  const [restarting, setRestarting] = useState(false);

  const run = game.run;
  const forced = run?.status === "deadline";

  if (game.loading && !run) {
    return (
      <div className="gameLoading">
        <LoadingState label="正在打开案卷" />
      </div>
    );
  }
  if (!run) {
    return (
      <div className="gameLoading">
        <ErrorState
          title="案卷打不开"
          description={game.error || "这份案卷可能已被删除。"}
          action={<RetryButton onClick={game.reload} />}
        />
      </div>
    );
  }

  if (run.status === "briefing") {
    return (
      <div className="caseShell briefingOnly">
        <Briefing run={run} busy={!!game.busy} onBegin={() => void game.move({ kind: "begin" })} />
        {game.error && <p className="error caseToast">{game.error}</p>}
      </div>
    );
  }

  async function act(body: MoveBody): Promise<CaseRun | undefined> {
    const next = await game.move(body);
    if (next) setView("investigate");
    return next;
  }

  async function restart() {
    if (!run) return;
    setRestarting(true);
    try {
      const fresh = await api<{ id: string }>("/case-runs", {
        method: "POST",
        body: JSON.stringify({ case_key: run.case.key }),
      });
      router.push(`/case/${fresh.id}`);
    } catch (exception) {
      game.setError((exception as Error).message);
      setRestarting(false);
    }
  }

  const closed = run.status === "closed";
  const danger = run.minutes_left <= 30;
  const pending = game.busy === "say" ? "对方正在想怎么回答你……" : "";

  return (
    <div className="caseShell" data-view={view}>
      <header className="caseTop">
        <div className="caseTitle">
          <Link href="/case" className="eyebrow">
            推理对决
          </Link>
          <h1>{run.case.title}</h1>
        </div>
        <div className={`caseClock ${danger ? "danger" : ""}`} aria-live="polite">
          <span>
            距靠岸 <b>{run.minutes_left}</b> 分钟
          </span>
          <progress max={run.case.minutes_total} value={run.minutes_left} aria-label="剩余时间" />
        </div>
        <p className="caseProgress">
          戳穿 {run.progress.lies_broken}/{run.progress.lies_total} · 证据{" "}
          {run.progress.evidence_found}
        </p>
        <div className="caseTools">
          <button className="button" onClick={() => setBriefingOpen(true)}>
            <BookOpen size={16} aria-hidden="true" /> 案情
          </button>
          {!closed && !forced && (
            <button
              className="button"
              onClick={() => void act({ kind: "think" })}
              disabled={!!game.busy}
              title={`翻一遍笔记，花 ${run.case.action_minutes} 分钟`}
            >
              <Lightbulb size={16} aria-hidden="true" /> 整理思路
            </button>
          )}
          {!closed && (
            <button
              className="button primary"
              onClick={() => setAccusing(true)}
              disabled={!!game.busy}
            >
              <Gavel size={16} aria-hidden="true" /> 指认
            </button>
          )}
        </div>
      </header>

      <aside className="caseRail caseCastRail" aria-label="人物">
        <h2>人物</h2>
        {run.characters.map((character) => (
          <button
            key={character.key}
            className={`caseDossierCard ${character.key === run.current ? "active" : ""}`}
            onClick={() => !closed && void act({ kind: "talk", target: character.key })}
            disabled={closed || !!game.busy}
          >
            <span className="caseDossierName">
              <b>{character.name}</b>
              {character.silent ? <small>不再开口</small> : <Patience character={character} />}
            </span>
            <small>{character.role}</small>
            <p>{character.description}</p>
            {character.met && (
              <small className="caseDossierCount">
                说法 {character.statements.length} · 已戳穿{" "}
                {character.statements.filter((s) => s.broken).length}
              </small>
            )}
          </button>
        ))}
      </aside>

      <main className="caseMain">
        <CaseLog
          log={run.log}
          characters={run.characters}
          pending={pending}
          onEvidence={(key) => {
            setFocus(key);
            setView("evidence");
          }}
        />
        {game.error && <p className="error caseInlineError">{game.error}</p>}
        {closed && run.result ? (
          <Verdict result={run.result} busy={restarting} onRestart={() => void restart()} />
        ) : (
          <CaseDock
            key={run.current ?? "scene"}
            run={run}
            busy={!!game.busy}
            onMove={(body) => void act(body)}
            onChallenge={(character, statement) => setChallenge({ character, statement })}
            onSay={game.say}
          />
        )}
      </main>

      <aside className="caseRail caseFolderRail" aria-label="证据夹">
        <h2>证据夹 · {run.evidence.length}</h2>
        <EvidenceFolder evidence={run.evidence} focus={focus} onFocus={setFocus} />
      </aside>

      <nav className="caseMobileNav" aria-label="切换面板">
        <button
          className={view === "investigate" ? "active" : undefined}
          onClick={() => setView("investigate")}
        >
          <MessageSquareText size={18} aria-hidden="true" /> 调查
        </button>
        <button
          className={view === "people" ? "active" : undefined}
          onClick={() => setView("people")}
        >
          <Users size={18} aria-hidden="true" /> 人物
        </button>
        <button
          className={view === "evidence" ? "active" : undefined}
          onClick={() => setView("evidence")}
        >
          <FolderOpen size={18} aria-hidden="true" /> 证据 {run.evidence.length}
        </button>
      </nav>

      {briefingOpen && <Briefing run={run} busy={false} onClose={() => setBriefingOpen(false)} />}

      {challenge && (
        <EvidencePicker
          speaker={challenge.character.name}
          statement={
            challenge.character.statements.find((s) => s.key === challenge.statement)?.text ?? ""
          }
          evidence={run.evidence}
          cost={run.case.action_minutes}
          busy={!!game.busy}
          onClose={() => setChallenge(undefined)}
          onPresent={async (evidence) => {
            setChallenge(undefined);
            await act({ kind: "present", target: challenge.statement, evidence });
          }}
        />
      )}

      {(accusing || forced) && !closed && (
        <Accusation
          run={run}
          busy={!!game.busy}
          forced={forced}
          onClose={() => setAccusing(false)}
          onAccuse={async (body) => {
            const next = await act(body);
            if (next) setAccusing(false);
          }}
        />
      )}
    </div>
  );
}
