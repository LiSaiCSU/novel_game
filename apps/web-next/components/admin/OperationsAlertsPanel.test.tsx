// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import OperationsAlertsPanel from "./OperationsAlertsPanel";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);
const feed = {
  generated_at: "2026-08-24T00:00:00+00:00",
  window_hours: 24,
  healthy: false,
  counts: { critical: 1, warning: 0 },
  alerts: [
    {
      code: "urgent_support_unassigned",
      severity: "critical" as const,
      title: "存在未分派的紧急支持请求",
      description: "有 1 项紧急请求尚未明确负责人。",
      value: 1,
      href: "#support-operations",
    },
  ],
};

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("operations alerts", () => {
  it("shows a privacy-safe risk signal with a direct handling link and refreshes it", async () => {
    apiMock.mockResolvedValueOnce(feed).mockResolvedValueOnce({ ...feed, counts: { critical: 0, warning: 1 } });
    render(<OperationsAlertsPanel />);

    expect(await screen.findByText("存在未分派的紧急支持请求")).toBeTruthy();
    expect(screen.getByRole("link", { name: "前往处理" }).getAttribute("href")).toBe(
      "#support-operations",
    );
    fireEvent.click(screen.getByRole("button", { name: "刷新信号" }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(2));
  });
});
