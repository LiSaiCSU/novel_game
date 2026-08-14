import { describe, expect, it } from "vitest";
import { SseDecoder } from "./sse";

describe("SseDecoder", () => {
  it("preserves a JSON event split across arbitrary network chunks", () => {
    const decoder = new SseDecoder();

    expect(decoder.push("event: nar")).toEqual([]);
    expect(decoder.push('rative\r\ndata: {"del')).toEqual([]);
    expect(decoder.push('ta":"春日"}\r\n\r\n')).toEqual([
      { event: "narrative", data: '{"delta":"春日"}' },
    ]);
  });

  it("supports comments, multiline data, and a final frame without a blank line", () => {
    const decoder = new SseDecoder();
    expect(decoder.push(': heartbeat\n\nevent: state\ndata: {"visible":\ndata: true}')).toEqual([]);
    expect(decoder.finish()).toEqual([{ event: "state", data: '{"visible":\ntrue}' }]);
  });
});
