import { Bookmark, ChevronDown, MapPin, PanelRight, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActionComposer } from "./action-composer";
import type { Choice, Recap, Scene } from "./game-types";
import { buildActionRecommendations } from "./recommendations";

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
  qualityWarning: string;
  busy: boolean;
  completed: boolean;
  onHideRecap: () => void;
  onDraftChange: (value: string) => void;
  onAct: (value: string) => void;
  onOpenSaves: () => void;
  onOpenStatus: () => void;
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
  qualityWarning,
  busy,
  completed,
  onHideRecap,
  onDraftChange,
  onAct,
  onOpenSaves,
  onOpenStatus,
}: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const recommendations = useMemo(
    () => buildActionRecommendations(choices, state),
    [choices, state],
  );

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, []);

  useEffect(() => {
    if (busy) {
      requestAnimationFrame(() => setSuggestionsOpen(false));
    }
  }, [busy]);

  function choose(value: string) {
    onDraftChange(value);
    setSuggestionsOpen(false);
    requestAnimationFrame(() => formRef.current?.querySelector("textarea")?.focus());
  }

  return (
    <section className="gameCenter">
      <header className="gameStoryToolbar">
        <div>
          <MapPin size={15} aria-hidden="true" />
          <span>{state?.location?.name ?? "当前场景"}</span>
          <small>{state?.time?.label}</small>
        </div>
        <nav aria-label="游戏工具">
          <button onClick={onOpenSaves} title="打开场景与存档">
            <Bookmark size={17} aria-hidden="true" />
            <span>存档</span>
          </button>
          <button onClick={onOpenStatus} title="打开人物与状态">
            <PanelRight size={17} aria-hidden="true" />
            <span>状态</span>
          </button>
        </nav>
      </header>
      <div className="story" aria-live="polite">
        {showRecap && recap && recap.turn_number > 0 && (
          <section className="returnRecap" aria-label="上次游戏回顾">
            <header>
              <div>
                <p className="eyebrow">欢迎回来</p>
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
              // Reference, not suggestions. Submitting a quest title as an
              // action ("继续推进X") hands the engine a goal instead of a move,
              // and the concrete next steps already sit in the suggestion dock.
              <div className="recapObjectives">
                <b>还没了结的事</b>
                {recap.objectives.slice(0, 4).map((objective) => (
                  <span key={`${objective.type}-${objective.key}`} title={objective.hint}>
                    <span>{objective.name}</span>
                    {objective.hint && <small>{objective.hint}</small>}
                  </span>
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
          <article className="chapter currentChapter">
            {`你：${current.input}\n\n${current.narrative}`}
            {busy && <span className="streamCursor" aria-hidden="true" />}
          </article>
        )}
        {busy && <p className="progressLine">{progress || "世界正在回应你的行动"}</p>}
        {error && <p className="error">{error}</p>}
        {qualityWarning && (
          <p className="qualityWarning" role="status">
            {qualityWarning}
          </p>
        )}
        <div ref={endRef} />
      </div>
      {completed && (
        <div className="endingBanner">
          <span>本局已完成</span>
          <b>{state?.playthrough?.ending_title}</b>
          <small>你仍可以读取左侧较早的手动存档，继续探索另一种可能。</small>
        </div>
      )}
      <div className="conversationDock">
        {!completed && recommendations.length > 0 && (
          <div className={`decisionArea ${suggestionsOpen ? "open" : ""}`}>
            <button
              type="button"
              className="suggestionToggle"
              aria-expanded={suggestionsOpen}
              onClick={() => setSuggestionsOpen((open) => !open)}
            >
              <Sparkles size={16} aria-hidden="true" />
              <span>{beat || "接下来可以……"}</span>
              <small>{recommendations.length} 个建议</small>
              <ChevronDown size={15} aria-hidden="true" />
            </button>
            {suggestionsOpen && (
              <div className="choiceRow">
                {recommendations.map((choice) => (
                  <button
                    type="button"
                    key={choice.label}
                    onClick={() => choose(choice.label)}
                    disabled={busy}
                  >
                    <b>{choice.label}</b>
                    {choice.hint && <small>{choice.hint}</small>}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <ActionComposer
          formRef={formRef}
          draft={draft}
          busy={busy}
          completed={completed}
          onDraftChange={onDraftChange}
          onSubmit={onAct}
        />
        {!completed && <p className="composerNotice">建议只是灵感，你始终可以自由输入任何行动。</p>}
      </div>
    </section>
  );
}
