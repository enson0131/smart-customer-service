const exact = new Map([
  ["查看我的订单", "orders"],
  ["查询退款进度", "progress"],
  ["退货运费谁承担", "policy"],
]);
export function matchIntent(message: string) {
  return exact.get(message);
}
