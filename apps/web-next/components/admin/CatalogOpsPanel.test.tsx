// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import CatalogOpsPanel from "./CatalogOpsPanel";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);
const catalog = {
  currency: "CNY",
  checkout_live: false as const,
  items: [
    {
      code: "starter_100",
      name: "新手叙点包",
      description: "透明定价",
      credits: 100,
      price_minor: 1000,
      badge: "新手",
      sort_order: 10,
      active: true,
    },
  ],
};

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("commerce catalog administration", () => {
  it("saves a reasoned package catalog without creating checkout", async () => {
    apiMock.mockResolvedValueOnce(catalog).mockResolvedValueOnce(catalog);
    render(<CatalogOpsPanel />);

    await screen.findByDisplayValue("CNY");
    fireEvent.change(screen.getByPlaceholderText("变更理由（写入审计日志）"), {
      target: { value: "Publish launch pricing for review" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存套餐目录" }));

    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(2));
    expect(apiMock.mock.calls[1][0]).toBe("/admin/commerce/catalog");
    expect(apiMock.mock.calls[1][1]?.method).toBe("PUT");
    expect(JSON.parse(String(apiMock.mock.calls[1][1]?.body))).toMatchObject({
      currency: "CNY",
      reason: "Publish launch pricing for review",
      items: [{ code: "starter_100", price_minor: 1000 }],
    });
  });
});
