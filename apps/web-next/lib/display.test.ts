import { describe, expect, it } from "vitest";
import { interfaceLabel, roleLabels } from "./display";

describe("interface labels", () => {
  it("localizes platform values and hides unknown implementation keys", () => {
    expect(interfaceLabel("published")).toBe("已发布");
    expect(interfaceLabel("plot_threads")).toBe("剧情线");
    expect(interfaceLabel("internal_state_key", "状态已更新")).toBe("状态已更新");
  });

  it("localizes account roles", () => {
    expect(roleLabels(["player", "creator", "admin"])).toBe("玩家 · 创作者 · 管理员");
  });
});
