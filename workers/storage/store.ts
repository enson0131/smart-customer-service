import { REFUND_STATUS, RETURN_DAYS } from "../constants";
export type Order = {
  id: string;
  product: string;
  cents: number;
  delivered: string | null;
};
export type Visitor = {
  id: string;
  selected: string | null;
  ticket: string | null;
  reason: string | null;
};
const ident = (prefix: string) =>
  prefix + crypto.randomUUID().replaceAll("-", "").slice(0, 16);
export class Store {
  constructor(readonly db: D1Database) {}
  async session(cookie: string) {
    const id = cookie.match(/(?:^|;\s*)visitor=(w-[a-f0-9-]{36})(?:;|$)/)?.[1];
    if (id) {
      const row = await this.db
        .prepare("SELECT * FROM visitors WHERE id=?")
        .bind(id)
        .first<Visitor>();
      if (row) return row;
    }
    const visitor = "w-" + crypto.randomUUID();
    await this.db.batch([
      this.db.prepare("INSERT INTO visitors(id) VALUES (?)").bind(visitor),
      this.db
        .prepare(
          "INSERT INTO orders VALUES (?,?,?,?,date('now','-2 days')),(?,?,?,?,date('now','-10 days')),(?,?,?,?,NULL)",
        )
        .bind(
          ident("O-"),
          visitor,
          "云杉阅读灯",
          12900,
          ident("O-"),
          visitor,
          "雾蓝随行杯",
          6900,
          ident("O-"),
          visitor,
          "山野收纳包",
          3900,
        ),
    ]);
    return { id: visitor, selected: null, ticket: null, reason: null };
  }
  async orders(id: string) {
    return (
      await this.db
        .prepare(
          "SELECT id,product,cents,delivered FROM orders WHERE visitor=? ORDER BY rowid",
        )
        .bind(id)
        .all<Order>()
    ).results;
  }
  async select(id: string, order: string) {
    await this.db
      .prepare(
        "UPDATE visitors SET selected=?,ticket=NULL,reason=NULL WHERE id=? AND EXISTS(SELECT 1 FROM orders WHERE visitor=? AND id=?)",
      )
      .bind(order, id, id, order)
      .run();
  }
  async preview(visitor: string, o: Order, reason: string) {
    const existing = await this.db
      .prepare("SELECT id FROM refunds WHERE visitor=? AND order_id=?")
      .bind(visitor, o.id)
      .first<{ id: string }>();
    if (existing)
      return { text: "该单已有申请 " + existing.id + "，" + REFUND_STATUS };
    const age = o.delivered
      ? Math.floor(Date.now() / 86400000) - Date.parse(o.delivered) / 86400000
      : -1;
    if (age < 0 || age > RETURN_DAYS)
      return {
        text: o.delivered
          ? "已超出七天退货期限。"
          : "订单尚未签收，暂不能申请整单退款。",
      };
    const ticket = "P-" + crypto.randomUUID();
    await this.db
      .prepare("UPDATE visitors SET selected=?,ticket=?,reason=? WHERE id=?")
      .bind(o.id, ticket, reason, visitor)
      .run();
    return {
      text: "符合整单退款条件，请核对确认卡。",
      card: { ticket, order_id: o.id, cents: o.cents, reason },
    };
  }
  async refund(visitor: string, ref: string) {
    const row = await this.db
      .prepare(
        "SELECT id,order_id,reason,cents FROM refunds WHERE visitor=? AND id=?",
      )
      .bind(visitor, ref)
      .first();
    return row && { ...row, status: REFUND_STATUS };
  }
  async progress(visitor: string, ref?: string) {
    const rows = (
      await this.db
        .prepare(
          "SELECT id,order_id FROM refunds WHERE visitor=? AND (? IS NULL OR id=?) ORDER BY rowid DESC LIMIT 10",
        )
        .bind(visitor, ref || null, ref || null)
        .all()
    ).results;
    return (
      rows
        .map((r) => r.order_id + " · " + r.id + " · " + REFUND_STATUS)
        .join("\n") || "未找到退款申请。"
    );
  }
  async confirm(visitor: string, ticket: string) {
    await this.db
      .prepare(
        `INSERT INTO refunds SELECT ?,v.id,o.id,v.ticket,o.cents,v.reason FROM visitors v
      JOIN orders o ON o.id=v.selected AND o.visitor=v.id WHERE v.id=? AND v.ticket=?
      AND o.delivered BETWEEN date('now',?) AND date('now') ON CONFLICT DO NOTHING`,
      )
      .bind(ident("R-"), visitor, ticket, "-" + RETURN_DAYS + " days")
      .run();
    const id = await this.db
      .prepare("SELECT id FROM refunds WHERE visitor=? AND ticket=?")
      .bind(visitor, ticket)
      .first<string>("id");
    return id && this.refund(visitor, id);
  }
  async cancel(id: string) {
    const row = await this.db
      .prepare(
        "UPDATE visitors SET ticket=NULL,reason=NULL WHERE id=? AND ticket IS NOT NULL AND NOT EXISTS(SELECT 1 FROM refunds WHERE ticket=visitors.ticket) RETURNING id",
      )
      .bind(id)
      .first();
    return row ? "已关闭待确认操作。" : "没有待确认的退款操作。";
  }
}
