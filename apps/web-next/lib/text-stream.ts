export type FrameScheduler = () => Promise<void>;

const nextAnimationFrame: FrameScheduler = () =>
  new Promise((resolve) => requestAnimationFrame(() => resolve()));

/**
 * Reveal an upstream delta over animation frames.
 *
 * HTTP/2, mobile networks, reverse proxies, and React may coalesce many SSE
 * messages into one task. Splitting a large delta at the presentation edge
 * preserves real streaming without slowing the model request or inventing
 * text that has not arrived yet.
 */
export async function revealTextDelta(
  delta: string,
  append: (piece: string) => void,
  scheduleFrame: FrameScheduler = nextAnimationFrame,
  charactersPerFrame = 12,
): Promise<void> {
  if (!delta) return;
  const chunkSize = Math.max(1, charactersPerFrame);
  for (let offset = 0; offset < delta.length; offset += chunkSize) {
    append(delta.slice(offset, offset + chunkSize));
    await scheduleFrame();
  }
}
