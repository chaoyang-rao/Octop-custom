type Reply = { id: string; result?: unknown; error?: string };
declare global {
  interface Window {
    companionNative?: {
      platform: string;
      invoke: (op: string, args: Record<string, unknown>) => Promise<unknown>;
      onEvent: (callback: (event: NativeEvent) => void) => () => void;
    };
    webkit?: {
      messageHandlers?: {
        companion?: { postMessage: (value: unknown) => void };
      };
    };
    __companionReply?: (reply: Reply) => void;
    __companionEvent?: (event: NativeEvent) => void;
  }
}
export type NativeEvent = {
  type: string;
  board?: string;
  contextKey?: string;
  data?: unknown;
  text?: string;
  error?: string;
};
const pending = new Map<
  string,
  {
    resolve: (value: unknown) => void;
    reject: (error: Error) => void;
    timer: ReturnType<typeof setTimeout>;
  }
>();
window.__companionReply = (reply) => {
  const request = pending.get(reply.id);
  if (!request) return;
  clearTimeout(request.timer);
  pending.delete(reply.id);
  if (reply.error) request.reject(new Error(reply.error));
  else request.resolve(reply.result);
};
window.__companionEvent = (event) =>
  window.dispatchEvent(new CustomEvent("companion", { detail: event }));
window.companionNative?.onEvent((event) => window.__companionEvent?.(event));
if (window.companionNative?.platform === "win32")
  document.documentElement.dataset.platform = "windows";
export const isNative = () =>
  !!window.webkit?.messageHandlers?.companion || !!window.companionNative;
export function native<T = unknown>(
  op: string,
  args: Record<string, unknown> = {},
): Promise<T> {
  if (window.companionNative)
    return window.companionNative.invoke(op, args) as Promise<T>;
  return new Promise((resolve, reject) => {
    const channel = window.webkit?.messageHandlers?.companion;
    if (!channel) {
      reject(new Error("请从哆啦应用打开；浏览器中只可预览界面。"));
      return;
    }
    const id = crypto.randomUUID();
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error("连接超时，请重试或查看桌宠运行日志。"));
    }, 90_000);
    pending.set(id, { resolve: (value) => resolve(value as T), reject, timer });
    channel.postMessage({ id, op, args });
  });
}
export async function api<T = unknown>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await native<{ status: number; data: T }>("api", {
    path,
    method,
    ...(body === undefined ? {} : { body }),
  });
  if (response.status >= 400) {
    const value = response.data as { detail?: unknown; message?: unknown };
    const detail = value?.detail ?? value?.message;
    const message =
      typeof detail === "string"
        ? detail
        : response.status === 401
        ? "登录已过期，请重新登录。"
        : `请求未完成（${response.status}）`;
    throw new Error(message);
  }
  return response.data;
}
