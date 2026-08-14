// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import Settings from "./page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("model settings", () => {
  it("offers DeepSeek and Volcengine presets with editable compatible endpoints", async () => {
    apiMock.mockImplementation(async (path) => {
      if (path === "/settings/llm-credentials") return [];
      if (path === "/settings/llm-usage")
        return { daily: { used: 0, limit: 10 }, monthly: { used: 0, limit: 20 }, turn_limit: 5 };
      if (path === "/auth/sessions") return [];
      if (path === "/auth/mfa")
        return {
          enabled: false,
          required_for_admin: false,
          step_up_valid: false,
          recovery_codes_remaining: 0,
        };
      if (path === "/settings/privacy")
        return { product_analytics: false, collection: { events: "", never: [], retention: "" } };
      return {};
    });
    render(<Settings />);

    const supplier = screen.getByLabelText("供应商") as HTMLSelectElement;
    expect(supplier.value).toBe("compatible:deepseek");
    expect((screen.getByLabelText(/API 基础地址/) as HTMLInputElement).value).toBe(
      "https://api.deepseek.com",
    );

    fireEvent.change(supplier, { target: { value: "compatible:volcengine" } });
    await waitFor(() =>
      expect((screen.getByLabelText(/API 基础地址/) as HTMLInputElement).value).toBe(
        "https://ark.cn-beijing.volces.com/api/v3",
      ),
    );
  });
});
