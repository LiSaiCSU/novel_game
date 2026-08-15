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

const builtInLabels: Record<string, string> = {
  active: "进行中",
  offered: "待处理",
  completed: "已完成",
  failed: "失败",
  expired: "已过期",
  rejected: "已拒绝",
  accepted: "已接受",
  undecided: "暂未决定",
  co_protagonist: "核心同伴",
  romance_candidate: "可发展关系",
  affection: "好感",
  trust: "信任",
  respect: "尊重",
  familiarity: "熟悉",
  boundaries: "界限",
};

const technicalIdentifier = /^[a-z][a-z0-9_.-]*$/i;

export function displayLabel(
  labels: Record<string, string> | undefined,
  key: string,
  fallback: string,
): string {
  const declared = labels?.[key]?.trim();
  if (declared && declared !== key) return declared;
  if (builtInLabels[key]) return builtInLabels[key];
  if (!technicalIdentifier.test(key)) return key;
  return fallback;
}

export function progressionMetric(
  value: unknown,
  valueLabels: Record<string, string> | undefined,
): string {
  if (!value || typeof value !== "object") {
    const raw = metric(value);
    return displayLabel(valueLabels, raw, raw);
  }
  const data = value as Record<string, unknown>;
  const tier = data.tier ? displayLabel(valueLabels, String(data.tier), "当前阶段") : "";
  const stage = data.stage ? displayLabel(valueLabels, String(data.stage), "进行中") : "";
  const progress = Number(data.progress ?? 0);
  const parts = [tier, stage].filter((item, index, all) => item && all.indexOf(item) === index);
  if (Number.isFinite(progress) && progress > 0) parts.push(`进度 ${Math.round(progress)}%`);
  return parts.join(" · ") || "已记录";
}

export function formatChapters(history: History): string[] {
  return history.chapters.map((item) =>
    item.input ? `你：${item.input}\n\n${item.text}` : item.text,
  );
}
