// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import SuperAdminPanel from "./SuperAdminPanel";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: vi.fn() };
});

const apiMock = vi.mocked(api);
const users = [
  {
    id: "ordinary-account",
    email: "operator@example.com",
    display_name: "Operator",
    status: "active",
    roles: ["player", "admin"],
  },
];
const governance = {
  items: [
    {
      id: "break-glass-account",
      email: "owner@example.com",
      display_name: "Owner",
      status: "active",
      granted_at: "2026-08-24T00:00:00Z",
    },
  ],
  pending_approvals: [],
  current_user_id: "break-glass-account",
  mfa_required: true,
};

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("super administrator governance", () => {
  it("submits elevation as a reasoned request for another operator to review", async () => {
    apiMock
      .mockResolvedValueOnce(governance)
      .mockResolvedValueOnce({ id: "approval-1", status: "pending" })
      .mockResolvedValueOnce({
        ...governance,
        pending_approvals: [
          {
            id: "approval-1",
            requester_id: "break-glass-account",
            requester_email: "owner@example.com",
            target_user_id: "ordinary-account",
            target_email: "operator@example.com",
            requested_enabled: true,
            reason: "Add an on-call break-glass operator",
            expires_at: "2026-08-25T00:00:00Z",
            created_at: "2026-08-24T00:00:00Z",
          },
        ],
      });
    render(<SuperAdminPanel users={users} />);

    await screen.findByText("超级管理员");
    fireEvent.change(screen.getByLabelText("选择要授予最高权限的账户"), {
      target: { value: "ordinary-account" },
    });
    fireEvent.change(screen.getByPlaceholderText("申请理由（写入不可变审计日志）"), {
      target: { value: "Add an on-call break-glass operator" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交双人审批" }));

    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(3));
    expect(apiMock.mock.calls[1][0]).toBe("/admin/users/ordinary-account/super-admin");
    expect(apiMock.mock.calls[1][1]?.method).toBe("PUT");
    expect(JSON.parse(String(apiMock.mock.calls[1][1]?.body))).toEqual({
      enabled: true,
      reason: "Add an on-call break-glass operator",
    });
    expect(await screen.findByText("待复核请求")).toBeTruthy();
    expect(screen.getByRole("button", { name: "撤回请求" })).toBeTruthy();
  });
});
