import { ArrowLeft, ArrowRight, Clock3, Search, X } from "lucide-react";
import { useState } from "react";
import type { CaseRun } from "./case-types";

type Props = {
  run: CaseRun;
  busy: boolean;
  /** Absent once the case has begun: the briefing is then a reference card. */
  onBegin?: () => void;
  onClose?: () => void;
};

/**
 * The case file a player reads before the first move.
 *
 * A deduction game is unplayable if the player does not know who they are,
 * what happened, who is aboard and what they are allowed to do, so every one
 * of those gets its own page rather than a paragraph above the first choice.
 */
export function Briefing({ run, busy, onBegin, onClose }: Props) {
  const story = run.case.briefing;
  const pages = story.length + 2;
  const [page, setPage] = useState(0);
  const castPage = story.length;
  const rulesPage = story.length + 1;
  const last = page === pages - 1;

  return (
    <div className="caseBriefing" role="dialog" aria-modal="true" aria-labelledby="briefing-title">
      <article className="caseDossier">
        <header className="caseDossierHead">
          <p className="caseStamp">案卷</p>
          <div>
            <p className="eyebrow">{run.case.setting}</p>
            <h1 id="briefing-title">{run.case.title}</h1>
          </div>
          {onClose && (
            <button className="caseIconButton" onClick={onClose} aria-label="关闭案情">
              <X size={18} aria-hidden="true" />
            </button>
          )}
        </header>

        <div className="caseDossierBody" aria-live="polite">
          {page < castPage && (
            <section>
              <h2>{story[page].title}</h2>
              {story[page].body.split(/\n\s*\n/).map((paragraph) => (
                <p key={paragraph.slice(0, 24)}>{paragraph.trim()}</p>
              ))}
            </section>
          )}

          {page === castPage && (
            <section>
              <h2>船上的人</h2>
              <p className="caseVictim">
                <b>死者</b>
                {run.case.victim}
              </p>
              <div className="caseCastGrid">
                {run.characters.map((character) => (
                  <div className="caseCastCard" key={character.key}>
                    <b>{character.name}</b>
                    <small>
                      {character.role}
                      {!character.suspect && " · 可以帮你"}
                    </small>
                    <p>{character.description}</p>
                  </div>
                ))}
              </div>
              <p className="caseHint">留意他们的样子。人身上的细节，有时比他们说的话更可靠。</p>
            </section>
          )}

          {page === rulesPage && (
            <section>
              <h2>怎么查</h2>
              <p className="caseGoal">
                <Search size={16} aria-hidden="true" />
                {run.case.goal}
              </p>
              <dl className="caseRules">
                {run.case.rules.map((rule) => (
                  <div key={rule.title}>
                    <dt>{rule.title}</dt>
                    <dd>{rule.body}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}
        </div>

        <footer className="caseDossierFoot">
          <div className="caseDots" aria-label={`第 ${page + 1} 页，共 ${pages} 页`}>
            {Array.from({ length: pages }, (_, index) => (
              <button
                key={index}
                className={index === page ? "active" : undefined}
                aria-label={`第 ${index + 1} 页`}
                onClick={() => setPage(index)}
              />
            ))}
          </div>
          <div className="caseDossierNav">
            {page > 0 && (
              <button className="button" onClick={() => setPage(page - 1)}>
                <ArrowLeft size={16} aria-hidden="true" /> 上一页
              </button>
            )}
            {!last && (
              <button className="button primary" onClick={() => setPage(page + 1)}>
                下一页 <ArrowRight size={16} aria-hidden="true" />
              </button>
            )}
            {last && onBegin && (
              <button className="button primary" onClick={onBegin} disabled={busy}>
                <Clock3 size={16} aria-hidden="true" /> 开始调查 · 时钟开始走
              </button>
            )}
            {last && !onBegin && onClose && (
              <button className="button primary" onClick={onClose}>
                回到调查
              </button>
            )}
          </div>
        </footer>
      </article>
    </div>
  );
}
