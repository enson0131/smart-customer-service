import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { FakeToolCallingModel } from "langchain";
import { Store } from "../workers/storage/store";
import { D1Saver } from "../workers/storage/checkpoints";
import { chat } from "../workers/orchestration/chat";
import { search } from "../workers/domain/knowledge";
import { buildKnowledge } from "../scripts/worker-knowledge";
import { openSQLite as testDatabase } from "../workers/storage/sqlite";

const settings = { DEEPSEEK_API_KEY: "test-only" };
function model() {
  return new FakeToolCallingModel({
    toolCalls: [
      [
        { name: "track_shipment", args: {}, id: "shipping" },
        { name: "preview_refund", args: {}, id: "refund" },
      ],
      [],
    ],
  });
}

test("中文二元组检索、未知问题、Markdown/TXT 与空索引", async () => {
  assert.match(search("退货运费谁承担")[0].excerpt, /商家承担/);
  assert.deepEqual(search("海外关税如何计算"), []);
  const dir = await mkdtemp(join(tmpdir(), "knowledge-"));
  try {
    assert.deepEqual((await buildKnowledge(dir)).chunks, []);
    await writeFile(join(dir, "示例.TXT"), "# 标题\n退货运费。\n\n第二段。");
    const index = await buildKnowledge(dir);
    assert.equal(index.chunks.length, 2);
    assert.equal(index.chunks[0][0].title, "示例 · 标题");
    assert.equal(index.df["退货"], 1);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("多工具调用暂停后关闭数据库，重新创建 Agent 从持久检查点续办", async () => {
  const dir = await mkdtemp(join(tmpdir(), "aftercare-"));
  const path = join(dir, "db.sqlite");
  let database = testDatabase(path);
  try {
    let store = new Store(database.db);
    const visitor = await store.session("");
    const first = (await chat(
      store,
      visitor,
      "查物流，再看看能不能退",
      undefined,
      settings,
      model(),
    )) as any;
    assert.equal(first.orders.length, 3);
    assert.equal(first.card, undefined);
    assert.ok(
      await new D1Saver(database.db).getTuple({
        configurable: { thread_id: visitor.id },
      }),
    );
    const order = first.orders[0];
    database.close();
    database = testDatabase(path);
    store = new Store(database.db);
    const resumed = await store.session("visitor=" + visitor.id);
    const finalModel = new FakeToolCallingModel({ toolCalls: [[]] });
    const result = (await chat(
      store,
      resumed,
      order.id,
      { kind: "select_order", order_id: order.id },
      settings,
      finalModel,
    )) as any;
    assert.match(result.text, /已签收/);
    assert.match(result.text, /符合整单退款/);
    assert.equal(result.card.order_id, order.id);
    assert.equal(result.card.cents, 12900);
    assert.equal(
      await new D1Saver(database.db).getTuple({
        configurable: { thread_id: visitor.id },
      }),
      undefined,
    );
    assert.equal(
      await database.db.prepare("SELECT COUNT(*) AS n FROM refunds").first("n"),
      0,
    );
    const confirmations = await Promise.all(
      Array.from({ length: 6 }, () =>
        store.confirm(visitor.id, result.card.ticket),
      ),
    );
    assert.equal(new Set(confirmations.map((r) => (r as any).id)).size, 1);
    assert.equal(
      await database.db.prepare("SELECT COUNT(*) AS n FROM refunds").first("n"),
      1,
    );
    const other = await store.session("");
    assert.equal(
      await store.refund(other.id, (confirmations[0] as any).id),
      null,
    );
    assert.equal(await store.confirm(other.id, result.card.ticket), null);
  } finally {
    database.close();
    await rm(dir, { recursive: true, force: true });
  }
});

test("取消与重新选单使票据失效，未签收和过期订单不能退款", async () => {
  const database = testDatabase();
  try {
    const store = new Store(database.db),
      visitor = await store.session("");
    const orders = await store.orders(visitor.id);
    const preview = await store.preview(visitor.id, orders[0], "质量问题");
    await store.cancel(visitor.id);
    assert.equal(await store.confirm(visitor.id, preview.card!.ticket), null);
    const next = await store.preview(visitor.id, orders[0], "个人原因");
    await store.select(visitor.id, orders[1].id);
    assert.equal(await store.confirm(visitor.id, next.card!.ticket), null);
    assert.equal(
      (await store.preview(visitor.id, orders[1], "个人原因")).card,
      undefined,
    );
    assert.equal(
      (await store.preview(visitor.id, orders[2], "个人原因")).card,
      undefined,
    );
  } finally {
    database.close();
  }
});

test("模型异常保留已核实结果，初次模型失败保留可重试检查点", async () => {
  class UnavailableModel extends FakeToolCallingModel {
    bindTools() {
      return this;
    }
    async _generate(): Promise<never> {
      throw new Error("upstream timeout");
    }
  }
  const database = testDatabase();
  try {
    const store = new Store(database.db),
      visitor = await store.session("");
    const fail = new UnavailableModel({ toolCalls: [[]] });
    await assert.rejects(
      chat(store, visitor, "查物流，再看看能不能退", undefined, settings, fail),
      /timeout/,
    );
    const first = (await chat(
      store,
      visitor,
      "查物流，再看看能不能退",
      undefined,
      settings,
      model(),
    )) as any;
    const order = first.orders[0];
    const result = (await chat(
      store,
      visitor,
      order.id,
      { kind: "select_order", order_id: order.id },
      settings,
      fail,
    )) as any;
    assert.match(result.text, /已签收/);
    assert.equal(result.card.cents, 12900);
  } finally {
    database.close();
  }
});

test("中断中的选单仍校验归属，取消等待后不创建申请", async () => {
  const database = testDatabase();
  try {
    const store = new Store(database.db);
    const [visitor, stranger] = await Promise.all([
      store.session(""),
      store.session(""),
    ]);
    await chat(
      store,
      visitor,
      "查物流，再看看能不能退",
      undefined,
      settings,
      model(),
    );
    const foreign = (await store.orders(stranger.id))[0];
    const result = await chat(
      store,
      visitor,
      foreign.id,
      { kind: "select_order", order_id: foreign.id },
      settings,
      model(),
    );
    assert.match(result.text, /未找到/);
    await chat(
      store,
      visitor,
      "取消",
      { kind: "cancel_pending" },
      settings,
      model(),
    );
    assert.equal(
      await new D1Saver(database.db).getTuple({
        configurable: { thread_id: visitor.id },
      }),
      undefined,
    );
    assert.equal(
      await database.db.prepare("SELECT COUNT(*) AS n FROM refunds").first("n"),
      0,
    );
  } finally {
    database.close();
  }
});
