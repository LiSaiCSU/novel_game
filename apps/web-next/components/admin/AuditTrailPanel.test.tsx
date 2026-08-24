// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import AuditTrailPanel from "./AuditTrailPanel";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);
const feed = {
  items: [
    {
      id: "audit-1",
      actor_id: "admin-1",
      actor_email: "admin@example.com",
      action: "wallet.adjustment",
      target_type: "user",
      target_id: "player-1",
      request_id: "request-1",
      details: { reason: "Support correction", credit_delta: 100 },
      created_at: "2026-08-24T00:00:00Z",
    },
  ],
  next_before: null,
  limit: 30,
};

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("audit trail administration", () => {
  it("queries a safe action prefix and keeps raw detail collapsed", async () => {
    apiMock
      .mockResolvedValueOnce(feed)
      .mockResolvedValueOnce({ hours: 24, actions: [{ action: "wallet.adjustment", count: 3 }] })
      .mockResolvedValueOnce(feed);
    render(<AuditTrailPanel />);

    expect(await screen.findByText("管理员操作审计")).toBeTruthy();
    expect(screen.getByText("查看审计详情")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("按动作前缀筛选，例如 wallet. 或 user."), {
      target: { value: "wallet." },
    });
    fireEvent.click(screen.getByRole("button", { name: "筛选记录" }));

    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(3));
    expect(apiMock.mock.calls[2][0]).toBe("/admin/audit-logs?limit=30&action_prefix=wallet.");
  });
});
