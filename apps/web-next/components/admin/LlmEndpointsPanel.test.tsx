// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import LlmEndpointsPanel from "./LlmEndpointsPanel";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

function endpoint(overrides: Record<string, unknown> = {}) {
  return {
    id: "e1",
    name: "主用端点",
    enabled: true,
    priority: 0,
    provider: "compatible",
    base_url: "https://api.example.com/v1",
    narrative_model: "prose-model",
    reasoning_model: "cheap-model",
    narrative_extra_body: {},
    reasoning_extra_body: {},
    key_configured: true,
    key_hint: "…abcd",
    last_ok_at: null,
    last_error_at: null,
    last_error: "",
    consecutive_failures: 0,
    ...overrides,
  };
}

function listing(items: unknown[]) {
  return { items, supported_providers: ["anthropic", "compatible", "openai"], max_endpoints: 8 };
}

describe("LLM endpoints panel", () => {
  it("shows the chain in the order it will be tried", async () => {
    apiMock.mockResolvedValueOnce(
      listing([endpoint(), endpoint({ id: "e2", name: "备用网关", priority: 10 })]),
    );

    render(<LlmEndpointsPanel />);

    await waitFor(() => expect(screen.getByText("主用端点")).toBeTruthy());
    const ranks = screen.getAllByText(/^[12]$/).map((node) => node.textContent);
    expect(ranks).toEqual(["1", "2"]);
    expect(screen.getByText("备用网关")).toBeTruthy();
  });

  it("reports each preflight stage separately so a partial failure is visible", async () => {
    apiMock.mockResolvedValueOnce(listing([endpoint()]));
    apiMock.mockResolvedValueOnce({
      ok: false,
      stages: [
        { stage: "narrative", ok: true, detail: "流式输出 412 字，耗时 6.2 秒" },
        { stage: "reasoning", ok: false, detail: "返回内容不是合法 JSON，该模型无法承担推理类角色" },
      ],
      endpoint: endpoint({ consecutive_failures: 1, last_error: "不是合法 JSON" }),
    });
    apiMock.mockResolvedValueOnce(listing([endpoint({ consecutive_failures: 1 })]));

    render(<LlmEndpointsPanel />);
    await waitFor(() => expect(screen.getByText("主用端点")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "预检" }));

    // A model that streams prose fine but cannot produce JSON passes the old
    // ping and then breaks every turn at the intent stage. Both stages have to
    // be reported for that to be visible before players find it.
    await waitFor(() =>
      expect(screen.getByText("流式输出 412 字，耗时 6.2 秒")).toBeTruthy(),
    );
    expect(
      screen.getByText("返回内容不是合法 JSON，该模型无法承担推理类角色"),
    ).toBeTruthy();
    expect(screen.getByText("预检未通过")).toBeTruthy();
  });

  it("leaves a stored key untouched when the key box is left empty", async () => {
    apiMock.mockResolvedValueOnce(listing([endpoint()]));
    apiMock.mockResolvedValueOnce(endpoint());
    apiMock.mockResolvedValueOnce(listing([endpoint()]));

    render(<LlmEndpointsPanel />);
    await waitFor(() => expect(screen.getByText("主用端点")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));

    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(3));
    const [, options] = apiMock.mock.calls[1];
    const body = JSON.parse(String((options as RequestInit).body));
    expect("api_key" in body).toBe(false);
    expect(body.narrative_model).toBe("prose-model");
  });

  it("surfaces why the platform refuses to delete the last endpoint", async () => {
    apiMock.mockResolvedValueOnce(listing([endpoint()]));
    apiMock.mockRejectedValueOnce(
      new Error("这是最后一个可用端点，删除后平台将无法生成内容"),
    );

    render(<LlmEndpointsPanel />);
    await waitFor(() => expect(screen.getByText("主用端点")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "删除" }));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("最后一个可用端点"),
    );
  });

  it("shows a failing endpoint's recorded reason without needing a retest", async () => {
    apiMock.mockResolvedValueOnce(
      listing([
        endpoint({
          consecutive_failures: 3,
          last_error: "端点返回 404，请检查 Base URL 与模型名称：Base URL 通常需要以 /v1 结尾",
        }),
      ]),
    );

    render(<LlmEndpointsPanel />);

    await waitFor(() =>
      expect(screen.getByText(/连续失败 3 次/)).toBeTruthy(),
    );
    expect(screen.getByText(/\/v1 结尾/)).toBeTruthy();
  });
});
