import { Check, MessageSquareText, Search, Send, Stamp } from "lucide-react";
import { type FormEvent, useState } from "react";
import type { CaseCharacter, CaseLocation, CaseOption, CaseRun, MoveBody } from "./case-types";

const optionTags: Record<CaseOption["kind"], string> = {
  ask: "问",
  press: "逼问",
  comfort: "安抚",
  bluff: "诈",
};

type Props = {
  run: CaseRun;
  busy: boolean;
  onMove: (body: MoveBody) => void;
  onChallenge: (character: CaseCharacter, statementKey: string) => void;
  onSay: (character: string, text: string) => Promise<boolean>;
};

export function Patience({ character }: { character: CaseCharacter }) {
  return (
    <span
      className="casePatience"
      role="img"
      aria-label={`耐心 ${character.patience}/${character.patience_max}`}
      title={`耐心 ${character.patience}/${character.patience_max}`}
    >
      {Array.from({ length: character.patience_max }, (_, index) => (
        <i key={index} className={index < character.patience ? "on" : undefined} />
      ))}
    </span>
  );
}

/** Every move the player can make right now, as choices. Free text is the fallback. */
export function CaseDock({ run, busy, onMove, onChallenge, onSay }: Props) {
  const [tab, setTab] = useState<"people" | "scene">(run.current ? "people" : "scene");
  const [draft, setDraft] = useState("");
  const current = run.characters.find((c) => c.key === run.current);
  const deadline = run.status === "deadline";
  const cost = run.case.action_minutes;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!current || !draft.trim()) return;
    if (await onSay(current.key, draft.trim())) setDraft("");
  }

  if (deadline) {
    return (
      <div className="caseDock">
        <p className="caseDeadline">时间到了。巡捕房的人已经上船——你只剩下指认这一件事。</p>
      </div>
    );
  }

  return (
    <div className="caseDock">
      <div className="caseDockTabs" role="tablist" aria-label="调查方式">
        <button
          role="tab"
          aria-selected={tab === "people"}
          className={tab === "people" ? "active" : undefined}
          onClick={() => setTab("people")}
        >
          <MessageSquareText size={15} aria-hidden="true" /> 问话
        </button>
        <button
          role="tab"
          aria-selected={tab === "scene"}
          className={tab === "scene" ? "active" : undefined}
          onClick={() => setTab("scene")}
        >
          <Search size={15} aria-hidden="true" /> 勘查
        </button>
      </div>

      {tab === "people" && (
        <div className="caseDockBody">
          <div className="casePeople" aria-label="选择问话对象">
            {run.characters.map((character) => (
              <button
                key={character.key}
                className={`casePerson ${character.key === run.current ? "active" : ""} ${character.silent ? "silent" : ""}`}
                onClick={() => onMove({ kind: "talk", target: character.key })}
                disabled={busy}
              >
                <b>{character.name}</b>
                {character.silent ? <small>不再开口</small> : <Patience character={character} />}
              </button>
            ))}
          </div>

          {!current && (
            <p className="caseHint">选一个人问话。第一次见面不花时间，他会先把自己的说法摆出来。</p>
          )}

          {current && (
            <div className="caseInterrogation">
              {current.statements.length > 0 && (
                <section aria-label={`${current.name}的说法`}>
                  <h3>{current.name}的说法</h3>
                  <ul className="caseStatements">
                    {current.statements.map((statement) => (
                      <li key={statement.key} className={statement.broken ? "broken" : undefined}>
                        <span>「{statement.text}」</span>
                        {statement.broken ? (
                          <em>
                            <Stamp size={13} aria-hidden="true" /> 已戳穿
                          </em>
                        ) : (
                          !current.silent && (
                            <button
                              className="caseChallenge"
                              onClick={() => onChallenge(current, statement.key)}
                              disabled={busy || run.evidence.length === 0}
                              title={
                                run.evidence.length === 0
                                  ? "证据夹还是空的"
                                  : `出示证据，花 ${cost} 分钟`
                              }
                            >
                              出示证据
                            </button>
                          )
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {current.options.length > 0 && (
                <section aria-label="可以说的话">
                  <h3>你可以说</h3>
                  <div className="caseOptions">
                    {current.options.map((option) => (
                      <button
                        key={option.key}
                        className={`caseOption ${option.kind}`}
                        onClick={() => onMove({ kind: "option", target: option.key })}
                        disabled={busy}
                      >
                        <span className="caseTag">{optionTags[option.kind]}</span>
                        <span>{option.label}</span>
                      </button>
                    ))}
                  </div>
                </section>
              )}

              {current.silent ? (
                <p className="caseHint">{current.name}已经不会再跟你说什么了。</p>
              ) : (
                <form className="caseSay" onSubmit={submit}>
                  <input
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    maxLength={200}
                    placeholder={`自己问${current.name}一句……`}
                    aria-label={`自由提问${current.name}`}
                    disabled={busy}
                  />
                  <button className="button" disabled={busy || !draft.trim()} aria-label="发送">
                    <Send size={15} aria-hidden="true" />
                  </button>
                  <small>
                    AI 扮演对方回答；问到点子上，会自动算作对应的选项或出示。花 {cost} 分钟。
                  </small>
                </form>
              )}
            </div>
          )}
        </div>
      )}

      {tab === "scene" && (
        <div className="caseDockBody caseScene">
          {run.locations.map((location: CaseLocation) => (
            <section key={location.key}>
              <h3>{location.name}</h3>
              <p>{location.description}</p>
              <div className="caseSpots">
                {location.spots.map((spot) => (
                  <button
                    key={spot.key}
                    className={spot.examined ? "done" : undefined}
                    disabled={busy || spot.examined}
                    onClick={() => onMove({ kind: "examine", target: spot.key })}
                  >
                    {spot.examined && <Check size={14} aria-hidden="true" />}
                    {spot.label}
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
