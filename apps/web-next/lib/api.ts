export type ApiProblem = { detail?: string | { code?: string; [key: string]: unknown }; title?: string };

export class ApiError extends Error {
  constructor(public readonly problem: ApiProblem) {
    const detail = typeof problem.detail === "string" ? problem.detail : problem.title ?? "请求没有完成";
    super(detail);
    this.name = "ApiError";
  }
}

export function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const entry = document.cookie.split("; ").find((item) => item.startsWith("ng_csrf="));
  return entry ? decodeURIComponent(entry.split("=").slice(1).join("=")) : "";
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRF-Token", csrfToken());
  const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: "include" });
  if (!response.ok) {
    const problem = (await response.json().catch(() => ({}))) as ApiProblem;
    const detail = typeof problem.detail === "string" ? problem.detail : problem.title ?? "请求没有完成";
    throw new ApiError({...problem, title: detail});
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function streamApi(
  path: string,
  body: unknown,
  onEvent: (event: string, payload: Record<string, unknown>) => void,
): Promise<void> {
  const response = await fetch(`/api/v1${path}`, {
    method: "POST",
    credentials: "include",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken()},
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const problem = (await response.json().catch(() => ({}))) as ApiProblem;
    throw new Error(typeof problem.detail === "string" ? problem.detail : problem.title ?? "请求没有完成");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const {done, value} = await reader.read();
    buffer += decoder.decode(value, {stream: !done});
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const lines = frame.split("\n");
      const event = lines.find(line => line.startsWith("event:"))?.slice(6).trim();
      const data = lines.filter(line => line.startsWith("data:")).map(line => line.slice(5).trim()).join("\n");
      if (event && data) onEvent(event, JSON.parse(data) as Record<string, unknown>);
    }
    if (done) break;
  }
}
