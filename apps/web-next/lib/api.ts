export type ApiProblem = {
  detail?: string | { code?: string; message?: string; [key: string]: unknown };
  title?: string;
  status?: number;
};

const apiMessages: Record<string, string> = {
  "authentication required": "请先登录，再继续这项操作。",
  "email verification required": "请先输入邮件中的验证码完成邮箱验证。",
  "CSRF validation failed": "页面安全凭证已过期，请刷新页面后重试。",
  "insufficient role": "当前账号没有执行这项操作的权限。",
  "administrator MFA enrollment required": "管理员账号需要先启用双重验证。",
  "administrator MFA verification required": "请先完成当前设备的管理员二次验证。",
  "administrator MFA step-up required": "请先完成当前设备的管理员二次验证。",
  "invalid email or password": "邮箱或密码不正确。",
  "email is already registered": "这个邮箱已经注册过账号。",
  "account is not active": "账号当前不可用，请联系管理员。",
  "account no longer exists": "这个账号已经不存在。",
  "verification code is invalid or expired": "验证码不正确或已经过期，请重新获取。",
  "verification token is invalid or expired": "验证链接无效或已经过期。",
  "verification token is invalid": "验证链接无效。",
  "too many requests": "操作过于频繁，请稍后再试。",
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
  "campaign unavailable": "这个活动当前不可领取。",
  "campaign is not currently claimable": "这个活动当前不在可领取时间内。",
  "campaign redemption limit reached": "这项活动已经领完了。",
  "campaign code already exists": "活动代码已存在，请换一个内部代码。",
  "an expired campaign cannot be reactivated": "活动已过期，不能重新启用。",
  "an ended campaign cannot be reactivated": "活动已经结束，不能重新启用。",
  "support case not found": "没有找到这项支持请求，或当前账号无权查看。",
  "support case is not accepting replies": "这项请求已经结束，不能继续回复。",
  "assigned operator is not active": "所选处理人员当前不可用。",
  "assigned operator must be an administrator": "处理人员必须是管理员。",
  "notification not found": "没有找到这条通知，或当前账号无权查看。",
  // Creator studio failures are addressed by code, because the server sends
  // an English operator message that a writer should never have to read.
  document_invalid: "草稿还有字段不符合要求，请按下方提示修改后会自动重新保存。",
  document_slug_immutable: "作品的网址标识创建后不能修改。",
  document_plugin_forbidden: "网页版作品不能安装 Python 规则插件。",
  revision_conflict: "这份草稿在别处也被修改过，请选择保留哪一版。",
  insufficient_credits: "叙点余额不足，请先充值或领取活动额度。",
  creator_model_unavailable: "所选模型当前不可用，或平台 AI 额度已用完。可在设置里改用自带密钥。",
  creator_draft_failed: "生成草稿失败，你的原文没有被保存，请重试。",
  creator_import_key_reused: "这个重试标识对应的是另一份原文，请重新发起导入。",
  creator_completion_failed: "AI 补全没有完成，草稿未被改动，请重试。",
  creator_nothing_to_complete: "这份草稿的主要部分都已经齐全，没有需要补全的内容。",
};

function problemText(problem: ApiProblem): string {
  if (typeof problem.detail === "string") return problem.detail;
  // A structured detail carries a stable code plus an English operator
  // message. Prefer the code: it is what the translation table is keyed on,
  // and falling through to the message produced one generic sentence for
  // every distinct creator failure.
  if (typeof problem.detail?.code === "string" && apiMessages[problem.detail.code])
    return problem.detail.code;
  if (typeof problem.detail?.message === "string") return problem.detail.message;
  return problem.title ?? "请求没有完成";
}

export type DocumentProblem = { field: string; message: string };

export function documentProblems(error: unknown): DocumentProblem[] {
  if (!(error instanceof ApiError) || typeof error.problem.detail !== "object") return [];
  const raw = error.problem.detail?.problems;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) =>
    item && typeof item === "object" && typeof (item as DocumentProblem).field === "string"
      ? [{ field: String((item as DocumentProblem).field), message: String((item as DocumentProblem).message ?? "") }]
      : [],
  );
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
