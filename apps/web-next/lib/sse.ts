export type ServerSentEvent = {
  event: string;
  data: string;
};

function parseFrame(frame: string): ServerSentEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator < 0 ? line : line.slice(0, separator);
    const rawValue = separator < 0 ? "" : line.slice(separator + 1);
    const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue;
    if (field === "event") event = value;
    if (field === "data") data.push(value);
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

/** Incrementally decode SSE frames even when the network splits any line. */
export class SseDecoder {
  private buffer = "";

  push(chunk: string): ServerSentEvent[] {
    this.buffer = (this.buffer + chunk).replaceAll("\r\n", "\n");
    const events: ServerSentEvent[] = [];
    let boundary = this.buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const frame = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const event = parseFrame(frame);
      if (event) events.push(event);
      boundary = this.buffer.indexOf("\n\n");
    }
    return events;
  }

  finish(): ServerSentEvent[] {
    if (!this.buffer.trim()) return [];
    const final = parseFrame(this.buffer.replaceAll("\r\n", "\n"));
    this.buffer = "";
    return final ? [final] : [];
  }
}
