// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import SupportOpsPanel from "./SupportOpsPanel";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);
const summary = {
  created_24h: 2,
  unassigned_open: 1,
  oldest_open_at: "2026-08-24T00:00:00+00:00",
  by_status: { open: 1, in_progress: 1 },
  by_priority: { normal: 1, urgent: 1 },
};
const queue = {
  items: [
    {
      id: "case-1",
      category: "playthrough",
      status: "open" as const,
      priority: "urgent" as const,
      subject: "故事没有继续",
      assigned_to: null,
      created_at: "2026-08-24T00:00:00+00:00",
      updated_at: "2026-08-24T00:00:00+00:00",
      message_count: 1,
      player: { id: "player-1", email: "player@example.com", display_name: "玩家" },
    },
  ],
};
const operators = { items: [{ id: "admin-1", email: "admin@example.com", display_name: "运营" }] };
const detail = {
  ...queue.items[0],
  assigned_operator: null,
  messages: [
    {
      id: "message-1",
      author_role: "player" as const,
      author_id: "player-1",
      body: "选择行动后页面停住了。",
      created_at: "2026-08-24T00:00:00+00:00",
    },
  ],
};

afterEach(() => {
  cleanup();
  apiMock.mockReset();
  vi.unstubAllGlobals();
});

describe("support operations", () => {
  it("loads queue health and opens a private case for an MFA-protected operator workflow", async () => {
    apiMock
      .mockResolvedValueOnce(summary)
      .mockResolvedValueOnce(queue)
      .mockResolvedValueOnce(operators)
      .mockResolvedValueOnce(detail);
    vi.stubGlobal("prompt", vi.fn(() => "排查玩家报告的故事中断问题"));
    render(<SupportOpsPanel />);

    expect(await screen.findByText("故事没有继续")).toBeTruthy();
    expect(screen.getByText("1 项未分派")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /故事没有继续/ }));

    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(4));
    expect(apiMock.mock.calls[3][0]).toBe("/admin/support/cases/case-1");
    expect(apiMock.mock.calls[3][1]?.method).toBe("POST");
    expect(JSON.parse(String(apiMock.mock.calls[3][1]?.body))).toEqual({
      reason: "排查玩家报告的故事中断问题",
    });
    expect(await screen.findByText("选择行动后页面停住了。")).toBeTruthy();
    expect(screen.getByDisplayValue("未分派")).toBeTruthy();
  });
});
