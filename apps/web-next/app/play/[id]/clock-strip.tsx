import type { StoryClock } from "./game-types";

const kindLabel: Record<StoryClock["kind"], string> = {
  deadline: "倒计时",
  danger: "逼近",
  project: "进展",
};

/**
 * The pressure the player is under, as segments they can count.
 *
 * A story can hold a nine-day fuse and a faction three steps from identifying
 * you without either ever reaching the player, who then has no way to tell an
 * urgent turn from a spare one. Deadlines come first because they run down
 * whether or not anyone acts on them.
 */
export function ClockStrip({ clocks, compact = false }: { clocks: StoryClock[]; compact?: boolean }) {
  if (!clocks.length) return null;
  const shown = compact ? clocks.slice(0, 3) : clocks;

  return (
    <div className={compact ? "clockStrip compact" : "clockStrip"} aria-label="当前压力">
      {shown.map((clock) => (
        <div
          key={clock.key}
          className={`clockItem ${clock.kind}${clock.complete ? " complete" : ""}`}
          title={clock.consequence ? `满格后：${clock.consequence}` : clock.name}
        >
          <span className="clockName">
            {clock.name}
            {!compact && <small>{kindLabel[clock.kind]}</small>}
          </span>
          <span
            className="clockSegments"
            role="img"
            aria-label={`${clock.name}：${clock.segments} 格中已满 ${clock.filled} 格`}
          >
            {Array.from({ length: clock.segments }, (_, index) => (
              <i key={index} className={index < clock.filled ? "on" : undefined} aria-hidden="true" />
            ))}
          </span>
          {clock.remaining_label && <small className="clockLeft">剩 {clock.remaining_label}</small>}
        </div>
      ))}
    </div>
  );
}
