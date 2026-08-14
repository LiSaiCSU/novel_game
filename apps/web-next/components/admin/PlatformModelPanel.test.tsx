// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import PlatformModelPanel from "./PlatformModelPanel";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);
const config = {
  enabled: true,
  provider: "compatible" as const,
  model: "deepseek-v4-flash",
  base_url: "https://api.deepseek.com",
  extra_body: { thinking: { type: "disabled" } },
  key_configured: true,
  key_hint: "…1234",
  source: "environment" as const,
  updated_at: null,
};

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("platform model administration", () => {
  it("never renders the existing secret and saves a rotated key", async () => {
    apiMock.mockResolvedValueOnce(config).mockResolvedValueOnce({ ...config, source: "database" });
    render(<PlatformModelPanel />);

    await screen.findByDisplayValue("deepseek-v4-flash");
    const key = screen.getByLabelText("API 密钥") as HTMLInputElement;
    expect(key.value).toBe("");
    expect(key.placeholder).toContain("…1234");

    fireEvent.change(key, { target: { value: "new-secret-key" } });
    fireEvent.change(screen.getByLabelText(/变更理由/), { target: { value: "轮换生产密钥" } });
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));

    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(2));
    const [, request] = apiMock.mock.calls[1];
    expect(request?.method).toBe("PUT");
    expect(JSON.parse(String(request?.body))).toMatchObject({
      api_key: "new-secret-key",
      provider: "compatible",
      model: "deepseek-v4-flash",
    });
    expect(key.value).toBe("");
  });

  it("runs a connection test and presents latency", async () => {
    apiMock.mockResolvedValueOnce(config).mockResolvedValueOnce({
      provider: "compatible",
      model: "deepseek-v4-flash",
      latency_ms: 1422,
      input_tokens: 12,
      output_tokens: 8,
    });
    render(<PlatformModelPanel />);

    await screen.findByDisplayValue("deepseek-v4-flash");
    fireEvent.click(screen.getByRole("button", { name: "测试当前配置" }));
    expect(await screen.findByText(/连接成功：deepseek-v4-flash · 1422 ms/)).toBeTruthy();
  });
});
