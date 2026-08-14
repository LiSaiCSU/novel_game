// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { AppShell } from "./app-shell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/play",
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("AppShell", () => {
  it("marks the current area and shows the signed-in identity", async () => {
    apiMock.mockResolvedValue({
      display_name: "林澄",
      email: "lin@example.com",
      roles: ["player", "creator"],
    });
    render(<AppShell>故事列表</AppShell>);

    expect(screen.getByRole("link", { name: "我的故事" }).getAttribute("aria-current")).toBe(
      "page",
    );
    await waitFor(() => expect(screen.getByText("林澄")).toBeTruthy());
    const account = screen.getByRole("button", { name: "打开账户菜单：林澄" });
    expect(account.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(account);
    expect(screen.getByRole("menu")).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "账户设置" }).getAttribute("href")).toBe(
      "/settings",
    );
    expect(screen.getByRole("menuitem", { name: "退出登录" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "审核台" })).toBeNull();
    expect(screen.queryByRole("link", { name: "管理" })).toBeNull();
  });

  it("only reveals privileged workspaces for the assigned roles", async () => {
    apiMock.mockResolvedValue({
      display_name: "审核员",
      email: "reviewer@example.com",
      roles: ["player", "reviewer", "admin"],
    });
    render(<AppShell>审核内容</AppShell>);

    await waitFor(() => expect(screen.getByRole("link", { name: "审核台" })).toBeTruthy());
    expect(screen.getByRole("link", { name: "管理" })).toBeTruthy();
  });
});
