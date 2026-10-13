import { Gavel, X } from "lucide-react";
import { useState } from "react";
import type { CaseRun, MoveBody } from "./case-types";
import { EvidenceCard } from "./evidence";

type Props = {
  run: CaseRun;
  busy: boolean;
  forced: boolean;
  onAccuse: (body: MoveBody) => void;
  onClose: () => void;
};

const steps = ["谁", "用什么", "为什么", "拿什么证明"] as const;

/** One chance: who, with what, why, and the exhibits that hold it up. */
export function Accusation({ run, busy, forced, onAccuse, onClose }: Props) {
  const options = run.accusation;
  const [step, setStep] = useState(0);
  const [culprit, setCulprit] = useState("");
  const [weapon, setWeapon] = useState("");
  const [motive, setMotive] = useState("");
  const [exhibits, setExhibits] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);

  const answered = [culprit, weapon, motive, exhibits.length ? "yes" : ""];
  const ready = culprit && weapon && motive;

  function toggleExhibit(key: string) {
    setExhibits((current) =>
      current.includes(key)
        ? current.filter((item) => item !== key)
        : current.length < options.max_evidence
          ? [...current, key]
          : current,
    );
  }

  return (
    <div className="caseModal" role="dialog" aria-modal="true" aria-labelledby="accuse-title">
      <div className="caseModalCard wide">
        <header>
          <div>
            <p className="eyebrow">{forced ? "时间到了" : "只有一次机会"}</p>
            <h2 id="accuse-title">指认</h2>
          </div>
          {!forced && (
            <button className="caseIconButton" onClick={onClose} aria-label="先不指认">
              <X size={18} aria-hidden="true" />
            </button>
          )}
        </header>

        <nav className="caseSteps" aria-label="指认步骤">
          {steps.map((label, index) => (
            <button
              key={label}
              className={`${index === step ? "active" : ""} ${answered[index] ? "done" : ""}`}
              onClick={() => setStep(index)}
            >
              {index + 1}. {label}
            </button>
          ))}
        </nav>

        <div className="caseAccuseBody">
          {step === 0 && (
            <div className="caseChoiceGrid">
              {options.suspects.map((suspect) => (
                <button
                  key={suspect.key}
                  className={culprit === suspect.key ? "selected" : undefined}
                  onClick={() => {
                    setCulprit(suspect.key);
                    setStep(1);
                  }}
                >
                  <b>{suspect.name}</b>
                  <small>{suspect.role}</small>
                </button>
              ))}
            </div>
          )}
          {step === 1 && (
            <div className="caseChoiceGrid">
              {options.weapons.map((item) => (
                <button
                  key={item.key}
                  className={weapon === item.key ? "selected" : undefined}
                  onClick={() => {
                    setWeapon(item.key);
                    setStep(2);
                  }}
                >
                  <b>{item.label}</b>
                </button>
              ))}
            </div>
          )}
          {step === 2 && (
            <div className="caseChoiceGrid single">
              {options.motives.map((item) => (
                <button
                  key={item.key}
                  className={motive === item.key ? "selected" : undefined}
                  onClick={() => {
                    setMotive(item.key);
                    setStep(3);
                  }}
                >
                  <b>{item.label}</b>
                </button>
              ))}
            </div>
          )}
          {step === 3 && (
            <div>
              <p className="caseHint">
                最多挑 {options.max_evidence} 件。凶手会一条一条地反驳，你的证据要撑住这几点：
              </p>
              <ul className="casePillars">
                {options.pillars.map((pillar) => (
                  <li key={pillar}>{pillar}</li>
                ))}
              </ul>
              <div className="casePickerList">
                {[...run.evidence].reverse().map((item) => (
                  <EvidenceCard
                    key={item.key}
                    item={item}
                    open={exhibits.includes(item.key)}
                    selected={exhibits.includes(item.key)}
                    onToggle={() => toggleExhibit(item.key)}
                  />
                ))}
              </div>
              <p className="caseHint">
                已选 {exhibits.length}/{options.max_evidence}
              </p>
            </div>
          )}
        </div>

        <footer>
          {confirming ? (
            <>
              <span className="caseConfirm">说出口就收不回了。确定吗？</span>
              <button className="button" onClick={() => setConfirming(false)}>
                再看看
              </button>
              <button
                className="button primary"
                disabled={busy}
                onClick={() => onAccuse({ kind: "accuse", culprit, weapon, motive, exhibits })}
              >
                <Gavel size={16} aria-hidden="true" /> 指认
              </button>
            </>
          ) : (
            <>
              {step < 3 && (
                <button className="button" onClick={() => setStep(step + 1)}>
                  下一步
                </button>
              )}
              <button
                className="button primary"
                disabled={!ready || busy}
                onClick={() => setConfirming(true)}
              >
                <Gavel size={16} aria-hidden="true" /> 就是这个人
              </button>
            </>
          )}
        </footer>
      </div>
    </div>
  );
}
