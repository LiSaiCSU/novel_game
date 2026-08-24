// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, documentProblems, localizeApiDetail, streamApi } from "./api";

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

  it("reads the structured code so creator failures stop collapsing into one sentence", async () => {
    // The server sends a stable code plus an English operator message. Before
    // this, only the message was read, so an unsaved draft, an exhausted quota
    // and a model outage all rendered as "请求没有完成，请稍后重试。".
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            status: 422,
            detail: {
              code: "document_invalid",
              message: "the draft does not satisfy the content schema",
              problems: [{ field: "manifest.title", message: "String should have at least 1 character" }],
            },
          }),
          { status: 422, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );

    const failure = (await api("/creator/projects/x/document", { method: "PUT" }).catch(
      (exception) => exception,
    )) as ApiError;

    expect(failure.message).toBe("草稿还有字段不符合要求，请按下方提示修改后会自动重新保存。");
    expect(documentProblems(failure)).toEqual([
      { field: "manifest.title", message: "String should have at least 1 character" },
    ]);
  });

  it("still hides an English operator message when the code is unrecognised", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ status: 500, detail: { code: "not_a_known_code", message: "boom" } }),
          { status: 500, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );

    const failure = (await api("/creator/projects/x/document", { method: "PUT" }).catch(
      (exception) => exception,
    )) as ApiError;

    expect(failure.message).toBe("请求没有完成，请稍后重试。");
    expect(documentProblems(failure)).toEqual([]);
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
