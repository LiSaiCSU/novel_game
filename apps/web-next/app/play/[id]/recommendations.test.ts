import { describe, expect, it } from "vitest";
import type { Dashboard, Scene } from "./game-types";
import { buildActionRecommendations } from "./recommendations";

const scene: Scene = {
  location: { name: "旧礼堂", description: "舞台边散落着尚未归档的旧节目单。" },
  present_characters: [{ name: "朝仓律" }],
};

const dashboard = {
  quests: [{ key: "restore", name: "月见馆修复计划", status: "active" }],
  threads: [
    {
      key: "ledger",
      name: "消失的账本",
      status: "active",
      stage: 2,
      next_beat_hint: "确认旧节目单上的赞助人署名",
    },
  ],
} as Dashboard;

describe("buildActionRecommendations", () => {
  it("turns legacy person and location labels into editable full actions", () => {
    const choices = buildActionRecommendations(
      [
        { label: "朝仓律", hint: "TALK", action_type: "TALK" },
        { label: "档案室", hint: "MOVE", action_type: "MOVE" },
      ],
      scene,
      dashboard,
    );

    expect(choices[0].label).toContain("和朝仓律聊聊");
    expect(choices[0].hint).not.toBe("TALK");
    expect(choices.some((choice) => choice.label.includes("前往档案室"))).toBe(true);
    expect(choices.some((choice) => choice.label.includes("月见馆修复计划"))).toBe(true);
    expect(choices.some((choice) => choice.label.includes("确认旧节目单上的赞助人署名"))).toBe(
      true,
    );
  });

  it("adds current quests and story-thread hints instead of generic prompts", () => {
    const choices = buildActionRecommendations([], scene, dashboard);

    expect(choices.some((choice) => choice.label.includes("月见馆修复计划"))).toBe(true);
    expect(choices.some((choice) => choice.label.includes("确认旧节目单上的赞助人署名"))).toBe(
      true,
    );
  });
});
