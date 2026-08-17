import { describe, expect, it } from "vitest";
import type { Scene } from "./game-types";
import { buildActionRecommendations } from "./recommendations";

const scene: Scene = {
  location: { name: "旧礼堂", description: "舞台边散落着尚未归档的旧节目单。" },
  present_characters: [{ name: "朝仓律" }],
};

describe("buildActionRecommendations", () => {
  it("shows the narrator's options exactly as written", () => {
    const narratorOptions = [
      {
        label: "我问朝仓律：“你为什么把那页记录撕走？”",
        hint: "当面追问刚才的隐瞒",
        source: "narrator",
      },
      { label: "我先不揭穿，跟着她去看看档案室。", hint: "换一个角度确认", source: "narrator" },
    ];

    const choices = buildActionRecommendations(narratorOptions, scene);

    expect(choices.map((choice) => choice.label)).toEqual(narratorOptions.map((o) => o.label));
  });

  it("never pads narrator options out with generic filler", () => {
    const choices = buildActionRecommendations(
      [{ label: "我把手里的账本推回去，说这事我不接。", source: "narrator" }],
      scene,
    );

    expect(choices).toHaveLength(1);
    expect(choices[0].label).not.toContain("旧礼堂");
  });

  it("turns bare engine affordances into submittable actions", () => {
    const choices = buildActionRecommendations(
      [
        { label: "朝仓律", hint: "TALK", action_type: "TALK", source: "engine" },
        { label: "档案室", hint: "MOVE", action_type: "MOVE", source: "engine" },
      ],
      scene,
    );

    expect(choices[0].label).toBe("我叫住朝仓律，把刚才的事问清楚。");
    expect(choices[0].hint).not.toBe("TALK");
    expect(choices[1].label).toBe("我现在就去档案室。");
  });

  it("suggests looking around when the world offered nothing else", () => {
    const choices = buildActionRecommendations([], scene);

    expect(choices).toHaveLength(1);
    expect(choices[0].label).toContain("旧礼堂");
  });
});
