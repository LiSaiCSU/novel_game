import { BellRing, NotebookPen, Paperclip, Stamp } from "lucide-react";
import { useEffect, useRef } from "react";
import type { CaseCharacter, LogEntry } from "./case-types";

type Props = {
  log: LogEntry[];
  characters: CaseCharacter[];
  pending: string;
  onEvidence: (key: string) => void;
};

/** The investigation as it happened, newest at the bottom. */
export function CaseLog({ log, characters, pending, onEvidence }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const names = Object.fromEntries(characters.map((c) => [c.key, c.name]));

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [log.length, pending]);

  return (
    <div className="caseLog" aria-live="polite">
      {log.map((entry) => {
        const speaker = entry.speaker ? names[entry.speaker] : undefined;
        switch (entry.kind) {
          case "npc":
            return (
              <p className="caseLine npc" key={entry.id}>
                {speaker && <b>{speaker}</b>}
                <span>{entry.text}</span>
              </p>
            );
          case "player":
            return (
              <p className="caseLine player" key={entry.id}>
                <span>{entry.text}</span>
              </p>
            );
          case "evidence":
            return (
              <button
                className="caseLine evidence"
                key={entry.id}
                onClick={() => entry.evidence && onEvidence(entry.evidence)}
              >
                <Paperclip size={14} aria-hidden="true" />
                {entry.text}
              </button>
            );
          case "break":
            return (
              <p className="caseLine break" key={entry.id}>
                <Stamp size={15} aria-hidden="true" />
                <span>{entry.text}</span>
              </p>
            );
          case "fail":
            return (
              <p className="caseLine fail" key={entry.id}>
                {entry.text}
              </p>
            );
          case "event":
            return (
              <p className="caseLine event" key={entry.id}>
                <BellRing size={15} aria-hidden="true" />
                <span>
                  {speaker && <b>{speaker}：</b>}
                  {entry.text}
                </span>
              </p>
            );
          case "note":
            return (
              <p className="caseLine note" key={entry.id}>
                <NotebookPen size={15} aria-hidden="true" />
                <span>{entry.text}</span>
              </p>
            );
          case "verdict":
            return (
              <p className="caseLine verdict" key={entry.id}>
                {entry.text}
              </p>
            );
          default:
            return (
              <p className="caseLine narration" key={entry.id}>
                {entry.text}
              </p>
            );
        }
      })}
      {pending && <p className="caseLine pending">{pending}</p>}
      <div ref={endRef} />
    </div>
  );
}
