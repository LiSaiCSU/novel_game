export type ApiProblem = {
  detail?: string | { code?: string; message?: string; [key: string]: unknown };
  title?: string;
  status?: number;
};

const apiMessages: Record<string, string> = {
  "authentication required": "请先登录，再继续这项操作。",
  "email verification required": "请先打开验证邮件完成邮箱验证。",
  "CSRF validation failed": "页面安全凭证已过期，请刷新页面后重试。",
  "insufficient role": "当前账号没有执行这项操作的权限。",
  "administrator MFA enrollment required": "管理员账号需要先启用双重验证。",
  "administrator MFA verification required": "请先完成当前设备的管理员二次验证。",
  "administrator MFA step-up required": "请先完成当前设备的管理员二次验证。",
  "invalid email or password": "邮箱或密码不正确。",
  "email is already registered": "这个邮箱已经注册过账号。",
  "account is not active": "账号当前不可用，请联系管理员。",
  "account no longer exists": "这个账号已经不存在。",
  "verification token is invalid or expired": "验证链接无效或已经过期。",
  "verification token is invalid": "验证链接无效。",
  "reset token is invalid or expired": "重置密码链接无效或已经过期。",
  "reset token is invalid": "重置密码链接无效。",
  "password confirmation failed": "当前密码不正确。",
  "MFA code is invalid": "验证码不正确。",
  "MFA code or recovery code is invalid": "验证码或恢复码不正确。",
  "playthrough not found": "没有找到这段故事，或当前账号无权访问。",
  "playthrough is not active": "这段故事当前不能继续行动。",
  "playthrough runtime is incomplete": "故事数据尚未准备完整，请稍后重试。",
  "completed playthrough cannot be saved": "已经结束的故事不能再创建新存档。",
  "save not found": "没有找到这个存档。",
  "release not found": "没有找到这个作品版本，或它暂时不可访问。",
  "scenario does not exist": "作品中没有这个故事入口。",
  "unknown narrative length preset": "不支持所选的叙事长度。",
  "ending not found": "没有找到这个结局。",
  "ending conditions are not satisfied": "当前还没有满足这个结局的条件。",
  "romance ending requires explicit consent": "进入恋爱结局前需要明确选择愿意发展关系。",
  "credential not found": "没有找到这份模型密钥。",
  "credential test failed": "模型连接测试失败，请检查地址、密钥和模型名称。",
  "data export not found": "没有找到这份数据导出任务。",
  "data export is unavailable": "个人数据文件暂时不可下载。",
};

function problemText(problem: ApiProblem): string {
  if (typeof problem.detail === "string") return problem.detail;
  if (typeof problem.detail?.message === "string") return problem.detail.message;
  return problem.title ?? "请求没有完成";
}

export function localizeApiDetail(detail: string): string {
  if (apiMessages[detail]) return apiMessages[detail];
  if (/^[\x00-\x7F]+$/.test(detail) && /[A-Za-z]/.test(detail)) {
    return "请求没有完成，请稍后重试。";
  }
  return detail;
}

export class ApiError extends Error {
  constructor(
    public readonly problem: ApiProblem,
    public readonly status: number = problem.status ?? 0,
  ) {
    super(localizeApiDetail(problemText(problem)));
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
    const detail = problemText(problem);
    throw new ApiError({ ...problem, title: detail, status: response.status }, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function streamApi(
  path: string,
  body: unknown,
  onEvent: (event: string, payload: Record<string, unknown>) => void | Promise<void>,
): Promise<void> {
  const response = await fetch(`/api/v1${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const problem = (await response.json().catch(() => ({}))) as ApiProblem;
    throw new ApiError({ ...problem, status: response.status }, response.status);
  }
  const reader = response.body.getReader();
  const textDecoder = new TextDecoder();
  const eventDecoder = new SseDecoder();

  async function dispatch(events: ReturnType<SseDecoder["push"]>) {
    for (const item of events) {
      await onEvent(item.event, JSON.parse(item.data) as Record<string, unknown>);
    }
  }

  while (true) {
    const { done, value } = await reader.read();
    await dispatch(eventDecoder.push(textDecoder.decode(value, { stream: !done })));
    if (done) {
      await dispatch(eventDecoder.finish());
      break;
    }
  }
}
import { SseDecoder } from "./sse";
