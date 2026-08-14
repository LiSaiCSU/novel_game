import type { Choice, Dashboard, Scene } from "./game-types";

const ACTION_SENTENCE_LENGTH = 16;

function sentenceChoice(choice: Choice): Choice | undefined {
  const label = choice.label.trim();
  const actionType = choice.action_type?.toUpperCase();

  if (actionType === "TALK" && label.length < ACTION_SENTENCE_LENGTH) {
    return {
      ...choice,
      label: `我先和${label}聊聊，问问对方对眼下事情的看法。`,
      hint: "留意对方的态度、目标，以及愿意透露或刻意回避的信息",
    };
  }
  if (actionType === "MOVE" && label.length < ACTION_SENTENCE_LENGTH) {
    return {
      ...choice,
      label: `我前往${label}，看看那里是否出现了新的线索或人物。`,
      hint: "换一个场景推进时间，也可能遇见不同的人和事件",
    };
  }
  if (actionType === "CULTIVATE" && !label) {
    return {
      ...choice,
      label: "我暂时不急着表态，先整理思绪、恢复状态，再决定下一步。",
      hint: "给角色一点喘息时间，同时梳理目前掌握的信息",
    };
  }
  if (!label) return undefined;
  return { ...choice, label };
}

function unique(choices: Choice[]): Choice[] {
  const labels = new Set<string>();
  return choices.filter((choice) => {
    const key = choice.label.replace(/[，。！？\s]/g, "");
    if (!key || labels.has(key)) return false;
    labels.add(key);
    return true;
  });
}

export function buildActionRecommendations(
  choices: Choice[],
  state?: Scene,
  dashboard?: Dashboard,
  prioritizeChoices = false,
): Choice[] {
  const originals = choices
    .map(sentenceChoice)
    .filter((choice): choice is Choice => Boolean(choice));
  const recommendations: Choice[] = [];

  if (prioritizeChoices) recommendations.push(...originals);
  else {
    const conversation = originals.find((choice) => choice.action_type === "TALK");
    if (conversation) recommendations.push(conversation);
  }

  const activeQuest = dashboard?.quests.find((quest) =>
    ["active", "offered", "进行中", "已接受"].includes(quest.status.toLowerCase()),
  );
  if (activeQuest) {
    recommendations.push({
      label: `我围绕“${activeQuest.name}”梳理已知线索，确认下一步该从哪里着手。`,
      hint: "把自由行动和当前任务联系起来，避免遗漏重要条件",
      action_type: "QUERY_QUESTS",
    });
  }

  const activeThread = dashboard?.threads.find(
    (thread) => thread.status.toLowerCase() === "active" && thread.next_beat_hint,
  );
  if (activeThread) {
    recommendations.push({
      label: `我继续推进“${activeThread.name}”，重点留意：${activeThread.next_beat_hint}。`,
      hint: `当前剧情阶段 ${activeThread.stage} 的明确推进方向`,
      action_type: "CUSTOM",
    });
  }

  if (!prioritizeChoices) {
    const movement = originals.find((choice) => choice.action_type === "MOVE");
    if (movement) recommendations.push(movement);
    recommendations.push(...originals);
  }

  const firstCharacter = state?.present_characters?.[0];
  if (firstCharacter) {
    recommendations.push({
      label: `我观察${firstCharacter.name}刚才的反应，再选择合适的方式和对方交谈。`,
      hint: "先读懂对方的情绪和边界，再决定谈话的深浅",
      action_type: "OBSERVE",
    });
  }

  if (state?.location?.name) {
    recommendations.push({
      label: `我仔细查看${state.location.name}，寻找与当前目标有关、容易被忽略的细节。`,
      hint: state.location.description || "观察场景中的线索与变化",
      action_type: "SEARCH",
    });
  }

  return unique(recommendations).slice(0, 4);
}
