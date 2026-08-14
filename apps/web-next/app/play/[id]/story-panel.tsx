import { useEffect, useRef } from "react";
import { ActionComposer } from "./action-composer";
import type { Choice, Recap, Scene } from "./game-types";

type Props = {
  state?: Scene;
  chapters: string[];
  current?: { input: string; narrative: string };
  choices: Choice[];
  beat: string;
  draft: string;
  recap?: Recap;
  showRecap: boolean;
  progress: string;
  error: string;
  busy: boolean;
  completed: boolean;
  onHideRecap: () => void;
  onDraftChange: (value: string) => void;
  onAct: (value: string) => void;
};

export function StoryPanel({
  state,
  chapters,
  current,
  choices,
  beat,
  draft,
  recap,
  showRecap,
  progress,
  error,
  busy,
  completed,
  onHideRecap,
  onDraftChange,
  onAct,
}: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [chapters, current]);

  function choose(value: string) {
    onDraftChange(value);
    requestAnimationFrame(() => formRef.current?.querySelector("textarea")?.focus());
  }

  return (
    <section className="gameCenter">
      <div className="story" aria-live="polite">
        {showRecap && recap && recap.turn_number > 0 && (
          <section className="returnRecap" aria-label="上次游戏回顾">
            <header>
              <div>
                <p className="eyebrow">WELCOME BACK</p>
                <h2>回到 {recap.scene.location}</h2>
                <small>
                  {recap.scene.time} · 已进行 {recap.turn_number} 回合
                </small>
              </div>
              <button className="dangerLink" onClick={onHideRecap}>
                收起
              </button>
            </header>
            {recap.last_action && (
              <p>
                <b>你上次：</b>
                {recap.last_action}
              </p>
            )}
            {recap.recent.length > 0 && <blockquote>{recap.recent.at(-1)?.text}</blockquote>}
            {recap.objectives.length > 0 && (
              <div className="recapObjectives">
                <b>接下来可以关注</b>
                {recap.objectives.slice(0, 4).map((objective) => (
                  <button
                    key={`${objective.type}-${objective.key}`}
                    title={objective.hint}
                    onClick={() => choose(objective.hint || `继续推进${objective.name}`)}
                  >
                    <span>{objective.name}</span>
                    {objective.hint && <small>{objective.hint}</small>}
                  </button>
                ))}
              </div>
            )}
          </section>
        )}
        {chapters.length === 0 && <p>{state?.location?.description}</p>}
        {chapters.map((chapter, index) => (
          <article key={`${index}-${chapter.slice(0, 20)}`} className="chapter">
            {chapter}
          </article>
        ))}
        {current && (
          <article className="chapter">
            {`你：${current.input}\n\n${current.narrative}`}
            {busy && <span className="streamCursor" aria-hidden="true" />}
          </article>
        )}
        {busy && <p className="progressLine">{progress || "世界正在回应你的行动"}</p>}
        {error && <p className="error">{error}</p>}
        <div ref={endRef} />
      </div>
      {completed && (
        <div className="endingBanner">
          <span>本局已完成</span>
          <b>{state?.playthrough?.ending_title}</b>
          <small>你仍可以读取左侧较早的手动存档，继续探索另一种可能。</small>
        </div>
      )}
      <div className="decisionArea" aria-hidden={completed}>
        {beat && <p className="beatQuestion">{beat}</p>}
        {!completed && (
          <div className="choiceRow">
            {choices.slice(0, 4).map((choice) => (
              <button
                type="button"
                key={choice.label}
                title={choice.hint}
                onClick={() => choose(choice.label)}
                disabled={busy}
              >
                {choice.label}
              </button>
            ))}
          </div>
        )}
      </div>
      <ActionComposer
        formRef={formRef}
        draft={draft}
        busy={busy}
        completed={completed}
        onDraftChange={onDraftChange}
        onSubmit={onAct}
      />
    </section>
  );
}
