// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import NotificationsPage from "./page";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);
const unreadInbox = {
  unread_total: 1,
  items: [
    {
      id: "notice-1",
      kind: "support.reply",
      title: "支持团队已回复你的请求",
      body: "选择后故事停止",
      href: "/support",
      read_at: null,
      created_at: "2026-08-24T00:00:00+00:00",
    },
  ],
};

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("notification inbox", () => {
  it("marks all player-owned notifications as read and refreshes the count", async () => {
    apiMock
      .mockResolvedValueOnce(unreadInbox)
      .mockResolvedValueOnce({ marked: 1 })
      .mockResolvedValueOnce({
        unread_total: 0,
        items: [{ ...unreadInbox.items[0], read_at: "2026-08-24T01:00:00+00:00" }],
      });
    render(<NotificationsPage />);

    expect(await screen.findByRole("heading", { name: "1 条未读" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /支持团队已回复你的请求/ }).getAttribute("href")).toBe(
      "/support",
    );
    fireEvent.click(screen.getByRole("button", { name: "全部标为已读" }));

    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(3));
    expect(apiMock.mock.calls[1][0]).toBe("/notifications/read-all");
    expect(apiMock.mock.calls[1][1]?.method).toBe("POST");
    expect(await screen.findByRole("heading", { name: "0 条未读" })).toBeTruthy();
  });
});
