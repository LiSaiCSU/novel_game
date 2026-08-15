// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, localizeApiDetail, streamApi } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("API errors", () => {
  it("keeps the HTTP status and presents authentication failures in player language", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: 401, detail: "authentication required" }), {
          status: 401,
          headers: { "Content-Type": "application/problem+json" },
        }),
      ),
    );

    const failure = await api("/playthroughs", { method: "POST" }).catch((exception) => exception);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(401);
    expect((failure as Error).message).toBe("请先登录，再继续这项操作。");
  });

  it("does not expose unknown backend implementation messages", () => {
    expect(localizeApiDetail("playthrough storage adapter failed")).toBe(
      "请求没有完成，请稍后重试。",
    );
  });

  it("uses the same localized errors for streaming actions", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: "playthrough is not active" }), { status: 409 }),
        ),
    );

    const failure = await streamApi("/playthroughs/one/actions/stream", {}, vi.fn()).catch(
      (exception) => exception,
    );

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as Error).message).toBe("这段故事当前不能继续行动。");
  });
});
