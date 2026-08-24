// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import SupportPage from "./page";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);
const created = {
  id: "case-1",
  playthrough_id: null,
  category: "playthrough" as const,
  status: "open" as const,
  priority: "normal",
  subject: "选择后故事停止",
  created_at: "2026-08-24T00:00:00+00:00",
  updated_at: "2026-08-24T00:00:00+00:00",
  message_count: 1,
  latest_message_at: "2026-08-24T00:00:00+00:00",
  player_can_reply: true,
  messages: [
    {
      id: "message-1",
      author_role: "player" as const,
      body: "选择行动后没有后续内容。",
      created_at: "2026-08-24T00:00:00+00:00",
    },
  ],
};

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("player support center", () => {
  it("submits a deliberately scoped support case without collecting story prose automatically", async () => {
    apiMock
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce(created)
      .mockResolvedValueOnce({ items: [created] });
    render(<SupportPage />);

    await screen.findByText("还没有支持请求。", { exact: false });
    fireEvent.change(screen.getByLabelText("简短标题"), { target: { value: "选择后故事停止" } });
    fireEvent.change(screen.getByLabelText("发生了什么"), {
      target: { value: "选择行动后没有后续内容。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交支持请求" }));

    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(3));
    expect(apiMock.mock.calls[1][0]).toBe("/support/cases");
    expect(apiMock.mock.calls[1][1]?.method).toBe("POST");
    expect(JSON.parse(String(apiMock.mock.calls[1][1]?.body))).toMatchObject({
      category: "playthrough",
      subject: "选择后故事停止",
      message: "选择行动后没有后续内容。",
    });
    expect(await screen.findByText("问题已提交。你可以在这里查看处理进度并补充信息。")).toBeTruthy();
  });
});
