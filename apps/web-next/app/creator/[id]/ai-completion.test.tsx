// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiCompletion } from "./ai-completion";
import type { Package } from "./editor-types";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const completed = {
  manifest: { title: "雾中来信", summary: "简介", rating: "16+", tags: [], theme: {}, assets: [] },
  content: {
    world: {},
    scenarios: [],
    locations: [],
    characters: [],
    facts: [],
    endings: [
      { key: "ending_ai_1", title: "真相大白", epilogue: "登记本终于对上了。" },
      { key: "ending_ai_2", title: "不了了之", epilogue: "没有人再提起那份清单。" },
    ],
    plot_threads: [],
    quests: [],
    rules: [],
    narrative: {},
  },
} as unknown as Package;

function stubFetch(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

describe("AI completion", () => {
  it("requires an explicit confirmation before touching the draft", async () => {
    stubFetch({ document: completed, added: { endings: 2 }, filled: ["endings"], diagnostics: [] });
    const onApply = vi.fn();
    render(<AiCompletion projectId="p1" onApply={onApply} onStatus={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "开始补全" }));

    await waitFor(() => expect(screen.getByText("真相大白")).toBeTruthy());
    // Generating a proposal must not write anything on its own; a writer has
    // to see what would change first.
    expect(onApply).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "写入草稿" }));
    expect(onApply).toHaveBeenCalledWith(completed);
  });

  it("discards a proposal without applying it", async () => {
    stubFetch({ document: completed, added: { endings: 2 }, filled: ["endings"], diagnostics: [] });
    const onApply = vi.fn();
    render(<AiCompletion projectId="p1" onApply={onApply} onStatus={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "开始补全" }));
    await waitFor(() => expect(screen.getByText("真相大白")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "丢弃" }));

    await waitFor(() => expect(screen.queryByText("真相大白")).toBeNull());
    expect(onApply).not.toHaveBeenCalled();
  });

  it("shows why a completion failed instead of a generic retry message", async () => {
    stubFetch(
      {
        status: 409,
        detail: {
          code: "creator_model_unavailable",
          message: "The selected model is unavailable or your platform AI quota is exhausted.",
        },
      },
      409,
    );
    render(<AiCompletion projectId="p1" onApply={() => {}} onStatus={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "开始补全" }));

    await waitFor(() =>
      expect(
        screen.getByText(
          "所选模型当前不可用，或平台 AI 额度已用完。可在设置里改用自带密钥。",
        ),
      ).toBeTruthy(),
    );
  });
});
