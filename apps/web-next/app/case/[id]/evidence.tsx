import { X } from "lucide-react";
import { useState } from "react";
import { type Evidence, evidenceKindLabel } from "./case-types";

export function EvidenceCard({
  item,
  open,
  selected,
  onToggle,
}: {
  item: Evidence;
  open: boolean;
  selected?: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      className={`caseEvidence ${open ? "open" : ""} ${selected ? "selected" : ""}`}
      onClick={onToggle}
      aria-expanded={open}
      aria-pressed={selected}
    >
      <span className={`caseKind kind-${item.kind}`}>{evidenceKindLabel[item.kind]}</span>
      <b>{item.name}</b>
      {open && <p>{item.description}</p>}
    </button>
  );
}

/** The folder on the right: everything found so far, newest first. */
export function EvidenceFolder({
  evidence,
  focus,
  onFocus,
}: {
  evidence: Evidence[];
  focus: string;
  onFocus: (key: string) => void;
}) {
  if (!evidence.length) {
    return <p className="caseHint">证据夹还是空的。去现场看看，或者找人问话。</p>;
  }
  return (
    <div className="caseFolder">
      {[...evidence].reverse().map((item) => (
        <EvidenceCard
          key={item.key}
          item={item}
          open={focus === item.key}
          onToggle={() => onFocus(focus === item.key ? "" : item.key)}
        />
      ))}
    </div>
  );
}

/** Choosing what to put on the table against one statement. */
export function EvidencePicker({
  speaker,
  statement,
  evidence,
  cost,
  busy,
  onPresent,
  onClose,
}: {
  speaker: string;
  statement: string;
  evidence: Evidence[];
  cost: number;
  busy: boolean;
  onPresent: (key: string) => void;
  onClose: () => void;
}) {
  const [choice, setChoice] = useState("");
  return (
    <div className="caseModal" role="dialog" aria-modal="true" aria-labelledby="picker-title">
      <div className="caseModalCard">
        <header>
          <div>
            <p className="eyebrow">出示证据</p>
            <h2 id="picker-title">
              {speaker}说：「{statement}」
            </h2>
            <p className="caseHint">哪一件东西能证明这句话不对？挑错了，对方的耐心会少一格。</p>
          </div>
          <button className="caseIconButton" onClick={onClose} aria-label="取消">
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <div className="casePickerList">
          {[...evidence].reverse().map((item) => (
            <EvidenceCard
              key={item.key}
              item={item}
              open
              selected={choice === item.key}
              onToggle={() => setChoice(item.key)}
            />
          ))}
        </div>
        <footer>
          <button className="button" onClick={onClose}>
            再想想
          </button>
          <button
            className="button primary"
            disabled={!choice || busy}
            onClick={() => onPresent(choice)}
          >
            就是它（{cost} 分钟）
          </button>
        </footer>
      </div>
    </div>
  );
}
