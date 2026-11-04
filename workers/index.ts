import { chat, type Action } from "./orchestration/chat";
import { log, withTask } from "./logging";
import { Store } from "./storage/store";
import type { Settings } from "./model/deepseek";
interface Env extends Settings {
  DB: D1Database;
  ASSETS: Fetcher;
}
export default {
  async fetch(req: Request, env: Env) {
    const path = new URL(req.url).pathname;
    if (path === "/health")
      return Response.json({
        ok: !!(await env.DB.prepare("SELECT 1").first()),
      });
    if (!path.startsWith("/api/")) return env.ASSETS.fetch(req);
    const headers = new Headers({ "cache-control": "no-store" });
    const json = (data: unknown, status = 200) =>
      Response.json(data, { status, headers });
    try {
      if (
        req.method === "POST" &&
        !req.headers.get("content-type")?.startsWith("application/json")
      )
        return json({ detail: "请使用 JSON 请求。" }, 415);
      const store = new Store(env.DB);
      const visitor = await store.session(req.headers.get("cookie") || "");
      headers.set(
        "set-cookie",
        "visitor=" +
          visitor.id +
          "; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Strict",
      );
      if (req.method === "GET" && path === "/api/orders")
        return json(await store.orders(visitor.id));
      if (req.method === "GET" && path.startsWith("/api/refunds/")) {
        const row = await store.refund(
          visitor.id,
          path.slice("/api/refunds/".length),
        );
        return row ? json(row) : json({ detail: "未找到该申请。" }, 404);
      }
      if (req.method === "POST") {
        const body = (await req.json().catch(() => null)) as {
          ticket?: string;
          message?: string;
          action?: Action;
        } | null;
        if (!body) return json({ detail: "请求格式有误。" }, 400);
        if (
          path === "/api/refunds/confirm" &&
          typeof body.ticket === "string"
        ) {
          const row = await store.confirm(visitor.id, body.ticket);
          return row
            ? json(row)
            : json({ detail: "确认卡已失效，请重新预览。" }, 409);
        }
        if (
          path === "/api/chat" &&
          typeof body.message === "string" &&
          body.message.trim() &&
          body.message.length <= 1200
        )
          return json(
            await withTask(visitor.id, async () => {
              log("chat.request", body);
              const result = await chat(
                store,
                visitor,
                body.message!.trim(),
                body.action,
                env,
              );
              log("chat.response", result);
              return result;
            }),
          );
        return json({ detail: "无效请求。" }, 400);
      }
      return json({ detail: "未找到接口。" }, 404);
    } catch (error) {
      const failure = error as {
        name?: string;
        status?: number;
        message?: string;
      };
      const detail = (failure.message || "")
        .replaceAll(env.DEEPSEEK_API_KEY || "unset", "[redacted]")
        .replace(/https?:\/\/[^\s]+/g, "[endpoint]");
      console.warn(
        "worker.failure",
        failure.name,
        failure.status,
        detail.slice(0, 300),
      );
      return json({ detail: "暂时无法完成查询，请稍后重试。" }, 503);
    }
  },
};
