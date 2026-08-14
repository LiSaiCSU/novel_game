// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StoryPanel } from "./story-panel";

const callbacks = {
  onHideRecap: vi.fn(),
  onDraftChange: vi.fn(),
  onAct: vi.fn(),
  onOpenSaves: vi.fn(),
  onOpenStatus: vi.fn(),
  onOpenSettings: vi.fn(),
};

describe("StoryPanel reading flow", () => {
  const scrollIntoView = vi.fn();

  beforeEach(() => {
    scrollIntoView.mockClear();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  function panel(overrides: Partial<ComponentProps<typeof StoryPanel>> = {}) {
    return (
      <StoryPanel
        chapters={["上一节正文"]}
        choices={[]}
        beat=""
        draft=""
        showRecap={false}
        progress=""
        error=""
        qualityWarning=""
        busy={false}
        completed={false}
        {...callbacks}
        {...overrides}
      />
    );
  }

  it("moves to the new turn once and does not chase every streamed chunk", () => {
    const view = render(panel());
    expect(scrollIntoView).toHaveBeenCalledTimes(1);

    view.rerender(panel({ busy: true, current: { input: "推开门", narrative: "" } }));
    expect(scrollIntoView).toHaveBeenCalledTimes(2);
    expect(scrollIntoView).toHaveBeenLastCalledWith({ behavior: "smooth", block: "start" });

    view.rerender(panel({ busy: true, current: { input: "推开门", narrative: "门轴发出轻响。" } }));
    expect(scrollIntoView).toHaveBeenCalledTimes(2);
  });

  it("opens the newly settled recommendations as soon as a turn finishes", () => {
    const view = render(
      panel({ busy: true, current: { input: "追问", narrative: "他放下了账本。" } }),
    );

    view.rerender(
      panel({
        beat: "朝仓律停下来，等着你回应",
        choices: [
          {
            label: "我问朝仓律：“这笔款项是谁要求暂缓公开的？”",
            hint: "承接刚刚出现的账本线索",
          },
        ],
        busy: false,
      }),
    );

    expect(screen.getByText("我问朝仓律：“这笔款项是谁要求暂缓公开的？”")).toBeTruthy();
    expect(screen.getByText("承接刚刚出现的账本线索")).toBeTruthy();
  });
});
