import { AsyncLocalStorage } from "node:async_hooks";
import { AsyncLocalStorageProviderSingleton } from "@langchain/core/singletons";
import { AIMessage, ToolMessage } from "@langchain/core/messages";
import { createAgent, createMiddleware } from "langchain";
import { Command } from "@langchain/langgraph";
import { aftercareTools } from "../domain/tools";
import { modelFor, type Settings } from "../model/deepseek";
import { search } from "../domain/knowledge";
import { D1Saver } from "../storage/checkpoints";
import { Store, type Visitor } from "../storage/store";
import { matchIntent } from "../intent/rules";

AsyncLocalStorageProviderSingleton.initializeGlobalInstance(
  new AsyncLocalStorage(),
);
const sequential = createMiddleware({
  name: "SequentialTools",
  async wrapModelCall(req, next) {
    const last = req.messages.at(-1);
    const previous = req.messages.filter(AIMessage.isInstance).at(-1);
    const queue = previous?.additional_kwargs
      .pendingTools as AIMessage["tool_calls"];
    // 模型一次返回多个工具时，将剩余调用随消息保存到 D1，恢复后逐个执行。
    function dispatch(calls: NonNullable<AIMessage["tool_calls"]>) {
      return new AIMessage({
        content: "",
        tool_calls: calls.slice(0, 1),
        additional_kwargs: { pendingTools: calls.slice(1) },
      });
    }
    if (
      last &&
      ToolMessage.isInstance(last) &&
      last.status !== "error" &&
      queue?.length
    )
      return dispatch(queue);
    console.log(
      "model.request",
      JSON.stringify({
        prompt: req.systemMessage?.content,
        messages: req.messages.map((m) => ({
          type: m.type,
          content: m.content,
          tools: AIMessage.isInstance(m) ? m.tool_calls : undefined,
        })),
      }),
    );
    let msg;
    try {
      const hasObservation = last && ToolMessage.isInstance(last);
      msg = await next(hasObservation ? {
        ...req,
        modelSettings: { ...req.modelSettings, maxRetries: 0, options: { timeout: 12000 } },
      } : req);
    } catch (error) {
      // 上游生成最终答复失败时，仍可展示本轮已经核实的事实和确认卡。
      const facts = req.messages.filter(ToolMessage.isInstance)
        .filter(m => m.status !== "error" && typeof m.content === "string");
      if (!facts.length) throw error;
      console.warn("model.unavailable", facts.map(m => m.name));
      const text = facts.filter(m => !["list_orders", "search_policy"].includes(m.name || ""))
        .map(m => m.content).join("\n");
      return new AIMessage([text, "模型暂时不可用，以上为已核实的工具结果。"].filter(Boolean).join("\n"));
    }
    console.log(
      "model.response",
      JSON.stringify({ content: msg.content, calls: msg.tool_calls }),
    );
    const observations = req.messages.filter(ToolMessage.isInstance);
    const hasOrder = observations.some(m => ["track_shipment", "check_fulfillment", "check_delivery_receipt"].includes(m.name || ""));
    // 对具体订单的资格结论，要求先取得领域工具的结果。仅查通用政策不能据此判单。
    if (!msg.tool_calls?.length && hasOrder && !observations.some(m => m.name === "preview_refund") &&
        /(?:能|可|符合|不支持|不能|无法|不符合|超过|超出).{0,12}(?:退货|退款|退回|退)/.test(String(msg.content))) {
      return dispatch([{name:"preview_refund", args:{}, id:"call_"+crypto.randomUUID()}]);
    }
    if ((msg.tool_calls?.length ?? 0) <= 1) return msg;
    return dispatch(msg.tool_calls!);
  },
});
export interface Action {
  kind?: string;
  order_id?: string;
}
export async function chat(
  store: Store,
  visitor: Visitor,
  message: string,
  action: Action | undefined,
  env: Settings,
) {
  const id = visitor.id,
    orders = await store.orders(id);
  const saver = new D1Saver(store.db),
    cfg = { configurable: { thread_id: id }, recursionLimit: 18 };
  const selectedButton =
    action?.kind === "select_order" && action.order_id === message;
  const chosen = selectedButton && orders.find((o) => o.id === message);
  if (selectedButton && !chosen) return { text: "未找到这笔订单。" };
  if (action?.kind === "cancel_pending" && message === "取消") {
    await saver.deleteThread(id);
    return { text: await store.cancel(id) };
  }
  const agent = createAgent({
    model: modelFor(env),
    tools: aftercareTools(store, visitor, orders),
    middleware: [sequential],
    checkpointer: saver,
    systemPrompt:
      "你是中文售后演示客服。订单、物流、退款和政策必须先查对应工具，只根据工具事实回复。多个诉求按顺序逐项查完。用户问某一单能不能退，必须调用 preview_refund，禁止用政策或日期自行推算。比如“查物流，再看看能不能退”，调用 track_shipment 和 preview_refund。用户未明确订单号时直接调用所需工具，省略 order_id，工具会让用户选单。禁止猜选订单。退款只可预览，点击确认才提交。",
  });
  const graph = agent.graph;
  let snap = await graph.getState(cfg);
  const pending = snap.tasks.flatMap((t) => t.interrupts || []);
  // 只有重试原请求或重发选单才恢复异常中止的任务，新问题启动独立任务。
  if (!pending.length && snap.next.length && !chosen) {
    const messages = snap.values.messages as { type: string; content: unknown }[] | undefined;
    const original = messages?.filter(m => m.type === "human").at(-1);
    if (original && original.content !== message) {
      await saver.deleteThread(id);
      snap = await graph.getState(cfg);
    }
  }
  const direct = matchIntent(message);
  if (pending.length && !chosen) return pending[0].value as { text: string };
  if (!pending.length && !snap.next.length) {
    if (chosen) {
      await store.select(id, chosen.id);
      return { text: "已选中「" + chosen.product + "」。", sources: [] };
    }
    if (direct === "orders")
      return { text: "请选择要查看的订单。", orders, sources: [] };
    if (direct === "progress")
      return { text: await store.progress(id), sources: [] };
    if (direct === "policy")
      return { text: "退货运费根据退货原因确定。", sources: search(message) };
  }
  const { results: turns } = await store.db
    .prepare(
      "SELECT message,answer FROM chat_turns WHERE visitor=? ORDER BY id DESC LIMIT 6",
    )
    .bind(id)
    .all<{ message: string; answer: string }>();
  const history = turns.reverse().flatMap((t) => [
    { role: "user", content: t.message },
    { role: "assistant", content: t.answer },
  ]);
  const input = pending.length
    ? new Command({ resume: { order_id: message } })
    : snap.next.length
      ? null
      : { messages: [...history, { role: "user", content: message }] };
  const result = await graph.invoke(input, cfg);
  if (result.__interrupt__?.length)
    return result.__interrupt__[0].value as { text: string };
  const artifacts: Record<string, unknown> = { sources: [] };
  for (const msg of result.messages.filter(ToolMessage.isInstance)) {
    if (msg.artifact) Object.assign(artifacts, msg.artifact);
    if (msg.name === "list_orders") artifacts.orders = orders;
  }
  let text = String(
    result.messages.at(-1)?.content || "暂时无法核实，请稍后重试。",
  );
  const observations = result.messages.filter(ToolMessage.isInstance).filter(m => m.status !== "error");
  if (observations.some(m => m.name === "preview_refund")) {
    // 资格、金额与确认方式由后端负责，避免模型改写已核实的结论。
    text = observations.filter(m => !["list_orders", "search_policy"].includes(m.name || ""))
      .map(m => String(m.content)).join("\n");
  }
  const original = result.messages.filter((m) => m.type === "human").at(-1);
  await store.db
    .prepare("INSERT INTO chat_turns(visitor,message,answer) VALUES (?,?,?)")
    .bind(id, String(original?.content || message), text)
    .run();
  await saver.deleteThread(id);
  return { text, ...artifacts };
}
