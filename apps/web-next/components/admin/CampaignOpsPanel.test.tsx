// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import CampaignOpsPanel from "./CampaignOpsPanel";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);
const campaigns = {
  credit_label: "叙点",
  items: [],
};

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("campaign administration", () => {
  it("creates a bounded, reasoned campaign rather than adjusting balances in bulk", async () => {
    apiMock.mockResolvedValueOnce(campaigns).mockResolvedValueOnce({
      id: "campaign-1",
      code: "launch_bonus",
      name: "新玩家体验赠点",
      description: "活动期间每位玩家仅可领取一次。",
      credit_amount: 100,
      status: "draft",
      starts_at: "2026-08-24T00:00:00+00:00",
      ends_at: "2026-08-31T00:00:00+00:00",
      max_redemptions: null,
      redemption_count: 0,
      redemptions_remaining: null,
      claimable: false,
    }).mockResolvedValueOnce(campaigns);
    render(<CampaignOpsPanel />);

    await screen.findByDisplayValue("launch_bonus");
    fireEvent.change(screen.getByPlaceholderText("创建理由（写入审计日志）"), {
      target: { value: "Publish a bounded launch welcome grant" },
    });
    fireEvent.change(screen.getByLabelText("领取上限（留空为不限）"), {
      target: { value: "500" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建活动" }));

    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(3));
    expect(apiMock.mock.calls[1][0]).toBe("/admin/commerce/campaigns");
    expect(apiMock.mock.calls[1][1]?.method).toBe("POST");
    expect(JSON.parse(String(apiMock.mock.calls[1][1]?.body))).toMatchObject({
      code: "launch_bonus",
      credit_amount: 100,
      max_redemptions: 500,
      reason: "Publish a bounded launch welcome grant",
    });
  });
});
