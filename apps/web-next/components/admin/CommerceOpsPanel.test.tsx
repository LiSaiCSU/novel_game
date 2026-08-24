// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import CommerceOpsPanel from "./CommerceOpsPanel";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);
const policy = {
  mode: "disabled" as const,
  enabled: false,
  credit_label: "Story credit",
  cost_microunits_per_credit: 10000,
  turn_reserve_credits: 100,
  hold_minutes: 20,
};
const summary = {
  credit_label: policy.credit_label,
  wallet_accounts: 4,
  credits_issued: 800,
  credits_settled: 90,
  credits_outstanding: 710,
  ledger_entries: 6,
  net_credit_delta_30d: 710,
  active_holds: 2,
  credits_reserved: 200,
  orders_by_status: {},
  checkout_live: false,
  billing_policy: policy,
  campaigns_by_status: { active: 1 },
};

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("commerce administration", () => {
  it("makes a reasoned, MFA-protected billing policy update request", async () => {
    const enabled = {
      ...policy,
      mode: "wallet" as const,
      enabled: true,
      turn_reserve_credits: 150,
    };
    apiMock
      .mockResolvedValueOnce(summary)
      .mockResolvedValueOnce(enabled)
      .mockResolvedValueOnce({
        ...summary,
        credits_reserved: 300,
        billing_policy: enabled,
      });
    render(<CommerceOpsPanel />);

    await screen.findByDisplayValue("Story credit");
    fireEvent.change(screen.getByLabelText("状态"), { target: { value: "wallet" } });
    fireEvent.change(screen.getByLabelText("单回合预留上限"), { target: { value: "150" } });
    fireEvent.change(screen.getByPlaceholderText("变更理由（写入审计日志）"), {
      target: { value: "Launch verified wallet billing" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存结算策略" }));

    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(3));
    expect(apiMock.mock.calls[1][0]).toBe("/admin/commerce/billing-policy");
    expect(apiMock.mock.calls[1][1]?.method).toBe("PUT");
    expect(JSON.parse(String(apiMock.mock.calls[1][1]?.body))).toMatchObject({
      mode: "wallet",
      turn_reserve_credits: 150,
      reason: "Launch verified wallet billing",
    });
    expect(await screen.findByText("已启用")).toBeTruthy();
  });
});
