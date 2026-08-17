import type { Choice, Scene } from "./game-types";

/** Bare-name legacy affordances ("朝仓律", "档案室") need a verb to be submittable. */
const BARE_LABEL_LENGTH = 16;
const technicalHint = /^(?:ActionType\.)?[A-Z_]+$/;

function readableHint(hint: string | undefined): string | undefined {
  const value = hint?.trim();
  if (!value || technicalHint.test(value)) return undefined;
  return value;
}

/**
 * Turn an engine affordance into something a player could actually say or do.
 *
 * These only appear when the narrator did not hand back a beat — a degraded
 * turn, or a chapter whose beat block failed to parse. They deliberately stay
 * small and physical ("go there", "ask this person") rather than restating a
 * quest title: a suggestion the player has to re-interpret is worse than no
 * suggestion at all.
 */
function sentenceChoice(choice: Choice): Choice | undefined {
  const label = choice.label.trim();
  const actionType = choice.action_type?.toUpperCase();

  if (actionType === "TALK" && label.length < BARE_LABEL_LENGTH) {
    return {
      ...choice,
      label: `我叫住${label}，把刚才的事问清楚。`,
      hint: `当面找${label}问话`,
    };
  }
  if (actionType === "MOVE" && label.length < BARE_LABEL_LENGTH) {
    return { ...choice, label: `我现在就去${label}。`, hint: `换到${label}继续` };
  }
  if (actionType === "CULTIVATE" && !label) {
    return {
      ...choice,
      label: "我先停一下，把手边的东西收拾好再动。",
      hint: "原地缓一口气",
    };
  }
  if (!label) return undefined;
  return { ...choice, label, hint: readableHint(choice.hint) };
}

function unique(choices: Choice[]): Choice[] {
  const labels = new Set<string>();
  return choices.filter((choice) => {
    const key = choice.label.replace(/[，。！？、“”\s]/g, "");
    if (!key || labels.has(key)) return false;
    labels.add(key);
    return true;
  });
}

/**
 * The narrator's hand-off, if there is one; otherwise the smallest set of
 * concrete moves the world can offer.
 *
 * Nothing is synthesised on top of a real beat. The narrator just wrote the
 * scene and knows who is standing there mid-sentence; padding its options out
 * to a fixed count with "review what you know about <quest>" only buries the
 * specific suggestion under generic ones.
 */
export function buildActionRecommendations(choices: Choice[], state?: Scene): Choice[] {
  const offered = choices
    .map((choice) => sentenceChoice(choice))
    .filter((choice): choice is Choice => Boolean(choice));
  const narratorLed = choices.some((choice) => choice.source === "narrator");

  if (narratorLed || offered.length >= 3) return unique(offered).slice(0, 4);

  const fallback = [...offered];
  if (state?.location?.name) {
    fallback.push({
      label: `我把${state.location.name}再仔细看一遍。`,
      hint: "找刚才漏掉的东西",
      action_type: "SEARCH",
    });
  }
  return unique(fallback).slice(0, 4);
}
