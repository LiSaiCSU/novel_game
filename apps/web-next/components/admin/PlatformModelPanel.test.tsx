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
  model: "deepseek-chat",
  base_url: "https://api.deepseek.com",
  extra_body: { thinking: { type: "disabled" } },
  narrative_model: "deepseek-chat",
  narrative_extra_body: { thinking: { type: "disabled" } },
  reasoning_enabled: true,
  reasoning_model: "deepseek-reasoner",
  reasoning_extra_body: { thinking: { type: "enabled" } },
  role_assignments: {
    narrative: ["narrative"],
    reasoning: ["intent", "npc", "npc_major", "director", "steward", "memory"],
  },
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
  it("never renders the existing secret and saves both model profiles", async () => {
    apiMock.mockResolvedValueOnce(config).mockResolvedValueOnce({ ...config, source: "database" });
    render(<PlatformModelPanel />);

    await screen.findByDisplayValue("deepseek-chat");
    expect(screen.getByDisplayValue("deepseek-reasoner")).toBeTruthy();
    const key = screen.getByLabelText("共享 API 密钥") as HTMLInputElement;
    expect(key.value).toBe("");
    expect(key.placeholder).toContain("…1234");

    fireEvent.change(key, { target: { value: "new-secret-key" } });
    fireEvent.change(screen.getByLabelText(/变更理由/), { target: { value: "拆分模型职责" } });
    fireEvent.click(screen.getByRole("button", { name: "保存模型路由" }));

    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(2));
    const [, request] = apiMock.mock.calls[1];
    expect(request?.method).toBe("PUT");
    expect(JSON.parse(String(request?.body))).toMatchObject({
      api_key: "new-secret-key",
      provider: "compatible",
      narrative_model: "deepseek-chat",
      reasoning_enabled: true,
      reasoning_model: "deepseek-reasoner",
      narrative_extra_body: { thinking: { type: "disabled" } },
      reasoning_extra_body: { thinking: { type: "enabled" } },
    });
    expect(key.value).toBe("");
  });

  it("tests narrative and reasoning profiles independently", async () => {
    apiMock
      .mockResolvedValueOnce(config)
      .mockResolvedValueOnce({
        profile: "narrative",
        provider: "compatible",
        model: "deepseek-chat",
        latency_ms: 822,
        input_tokens: 12,
        output_tokens: 8,
      })
      .mockResolvedValueOnce({
        profile: "reasoning",
        provider: "compatible",
        model: "deepseek-reasoner",
        latency_ms: 1422,
        input_tokens: 12,
        output_tokens: 20,
      });
    render(<PlatformModelPanel />);

    await screen.findByDisplayValue("deepseek-chat");
    fireEvent.click(screen.getByRole("button", { name: "测试已保存的叙事模型" }));
    expect(await screen.findByText(/叙事模型连接成功：deepseek-chat · 822 ms/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "测试已保存的推理模型" }));
    expect(await screen.findByText(/推理模型连接成功：deepseek-reasoner · 1422 ms/)).toBeTruthy();

    expect(apiMock.mock.calls[1][0]).toBe("/admin/llm-config/test?profile=narrative");
    expect(apiMock.mock.calls[2][0]).toBe("/admin/llm-config/test?profile=reasoning");
    expect(screen.getByText(/不代表完整游戏回合/)).toBeTruthy();
  });
});
