import { describe, expect, it, vi } from "vitest";
import { revealTextDelta } from "./text-stream";

describe("revealTextDelta", () => {
  it("paces a coalesced network delta over multiple render frames", async () => {
    const pieces: string[] = [];
    const nextFrame = vi.fn(async () => undefined);

    await revealTextDelta("abcdefghijkl", (piece) => pieces.push(piece), nextFrame, 5);

    expect(pieces).toEqual(["abcde", "fghij", "kl"]);
    expect(nextFrame).toHaveBeenCalledTimes(3);
  });
});
