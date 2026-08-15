import { describe, expect, it } from "vitest";
import { displayLabel, progressionMetric } from "./game-format";

describe("player-facing state labels", () => {
  it("never exposes an undeclared technical identifier", () => {
    expect(displayLabel({}, "festival_reputation", "成长进度")).toBe("成长进度");
    expect(displayLabel({ active: "进行中" }, "active", "状态已更新")).toBe("进行中");
  });

  it("renders progression objects as localized player text", () => {
    expect(
      progressionMetric(
        { track: "education", tier: "undergraduate", stage: "active", progress: 35 },
        { undergraduate: "本科生", active: "进行中" },
      ),
    ).toBe("本科生 · 进行中 · 进度 35%");
  });
});
