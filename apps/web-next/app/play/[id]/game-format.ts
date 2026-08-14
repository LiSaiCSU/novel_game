import type { History } from "./game-types";

export function metric(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value !== "object") return String(value);
  const data = value as Record<string, unknown>;
  const maximum = data.max ?? data.maximum;
  if (data.current !== undefined && maximum !== undefined) {
    return `${String(data.current)} / ${String(maximum)}`;
  }
  if (data.value !== undefined) return String(data.value);
  return Object.entries(data)
    .map(([key, item]) => `${key}: ${String(item)}`)
    .join(" · ");
}

export function formatChapters(history: History): string[] {
  return history.chapters.map((item) =>
    item.input ? `你：${item.input}\n\n${item.text}` : item.text,
  );
}
