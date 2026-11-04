import assert from "node:assert/strict";
import { EnvHttpProxyAgent, setGlobalDispatcher } from "undici";

// Node 22 的 fetch 默认不读取代理变量；沿用用户的 HTTP(S)_PROXY 与 NO_PROXY。
setGlobalDispatcher(new EnvHttpProxyAgent());

const origin = process.argv[2] || "http://127.0.0.1:8000";
let cookie = "";
async function request(path: string, body?: unknown) {
  const response = await fetch(origin + path, {
    method: body ? "POST" : "GET",
    headers: { cookie, "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(120000),
  });
  cookie = response.headers.get("set-cookie")?.split(";")[0] || cookie;
  const result = (await response.json()) as any;
  assert.equal(response.status, 200, JSON.stringify(result));
  return result;
}
assert.ok((await request("/health")).ok);
assert.equal((await fetch(origin)).status, 200);
assert.ok(
  (await request("/api/chat", { message: "退货运费谁承担" })).sources.length,
);
const first = await request("/api/chat", { message: "查物流，再看看能不能退" });
assert.ok(first.orders, "应先展示选单");
const order = first.orders.find((row: any) => row.product === "云杉阅读灯");
const result = await request("/api/chat", {
  message: order.id,
  action: { kind: "select_order", order_id: order.id },
});
assert.match(result.text, /签收/);
assert.equal(result.card.order_id, order.id);
assert.equal(result.card.cents, 12900);
const confirmed = await request("/api/refunds/confirm", {
  ticket: result.card.ticket,
});
assert.deepEqual(
  await request("/api/refunds/confirm", { ticket: result.card.ticket }),
  confirmed,
);
assert.equal(
  (await fetch(origin + "/api/refunds/" + confirmed.id)).status,
  404,
);
assert.ok(
  (await request("/api/chat", { message: "查询退款进度" })).text.includes(
    confirmed.id,
  ),
);
console.log("通过：选单后续办、129 元退款预览、确认幂等、访客隔离与进度查询。");
console.log(result.text);
