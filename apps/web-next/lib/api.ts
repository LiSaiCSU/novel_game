export type ApiProblem = {
  detail?: string | { code?: string; [key: string]: unknown };
  title?: string;
  status?: number;
};

export class ApiError extends Error {
  constructor(
    public readonly problem: ApiProblem,
    public readonly status: number = problem.status ?? 0,
  ) {
    const detail =
      typeof problem.detail === "string" ? problem.detail : (problem.title ?? "请求没有完成");
    const localized =
      detail === "authentication required"
        ? "请先登录，再继续这项操作。"
        : detail === "email verification required"
          ? "请先打开验证邮件完成邮箱验证。"
          : detail === "administrator MFA enrollment required"
            ? "管理员账号需要先启用双重验证。"
            : detail === "administrator MFA step-up required"
              ? "请先完成当前设备的管理员二次验证。"
              : detail;
    super(localized);
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
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRF-Token", csrfToken());
  const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: "include" });
  if (!response.ok) {
    const problem = (await response.json().catch(() => ({}))) as ApiProblem;
    const detail =
      typeof problem.detail === "string" ? problem.detail : (problem.title ?? "请求没有完成");
    throw new ApiError({ ...problem, title: detail, status: response.status }, response.status);
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
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const problem = (await response.json().catch(() => ({}))) as ApiProblem;
    throw new Error(
      typeof problem.detail === "string" ? problem.detail : (problem.title ?? "请求没有完成"),
    );
  }
  const reader = response.body.getReader();
  const textDecoder = new TextDecoder();
  const eventDecoder = new SseDecoder();

  function dispatch(events: ReturnType<SseDecoder["push"]>) {
    for (const item of events) {
      onEvent(item.event, JSON.parse(item.data) as Record<string, unknown>);
    }
  }

  while (true) {
    const { done, value } = await reader.read();
    dispatch(eventDecoder.push(textDecoder.decode(value, { stream: !done })));
    if (done) {
      dispatch(eventDecoder.finish());
      break;
    }
  }
}
import { SseDecoder } from "./sse";
