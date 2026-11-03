import { tool } from "langchain";
import { interrupt } from "@langchain/langgraph";
import { z } from "zod";
import { search } from "./knowledge";
import { Store, type Visitor, type Order } from "../storage/store";

export function aftercareTools(store:Store, visitor:Visitor, orders:Order[]) {
  const id=visitor.id;
  // 工具首次缺少订单时暂停。只有服务端校验过归属的选单按钮才可恢复。
  let selected=visitor.selected;
  const choose = async (orderId?:string)=>{
    let order=orders.find(o=>o.id===(orderId || selected));
    if(orderId && !order) throw Error("未找到这笔订单");
    if(!order){
      const answer=interrupt({orders,text:"请先选择要查询的订单。"});
      order=orders.find(o=>o.id===answer.order_id);
      if(!order) throw Error("无效订单");
    }
    if(order.id!==selected) await store.select(id,order.id);
    selected=order.id;
    return order;
  };
  const orderSchema=z.object({order_id:z.string().optional().describe("用户明确指定的订单号，否则留空")});
  const deliveryTools = [
    ["track_shipment","查询物流轨迹"],
    ["check_fulfillment","查询仓库交运记录"],
    ["check_delivery_receipt","查询签收回执"],
    ["shipping_cost","查询订单实际支付的运费金额"]
  ].map(([name,description])=>tool(async ({order_id})=>{
    const order=await choose(order_id);
    const signed=order.delivered;
    const facts:Record<string,string> = {
      track_shipment:signed?signed+" 已签收":"运输中，已离开分拨中心",
      check_fulfillment:"已出库并交运",
      check_delivery_receipt:signed?signed+" 小区代收点代收":"尚无签收回执",
      shipping_cost:"订单没有记录具体运费金额。"
    };
    return order.product+"（"+order.id+"） · "+facts[name];
  },{name,description,schema:orderSchema}));
  return [
    ...deliveryTools,
    tool(async()=>JSON.stringify(orders),{name:"list_orders",description:"列出本访客订单，不能代替用户选单。",schema:z.object({})}),
    tool(async ({order_id,reason})=>{
      const order=await choose(order_id);
      const {text,card}=await store.preview(id,order,reason || "客户申请整单退款");
      return [text,card ? {card}:{}] as [string,object];
    },{name:"preview_refund",description:"核验订单退款资格并生成整单退款确认卡。",schema:orderSchema.extend({reason:z.string().max(240).optional()}),responseFormat:"content_and_artifact"}),
    tool(async ({query})=>{
      const sources=search(query);
      return [sources.length?JSON.stringify(sources):"知识库缺少该问题的依据。",{sources}] as [string,object];
    },{name:"search_policy",description:"检索售后政策原文",schema:z.object({query:z.string()}),responseFormat:"content_and_artifact"}),
    tool(({reference})=>store.progress(id,reference),{name:"refund_progress",description:"查询已提交的退款申请",schema:z.object({reference:z.string().optional()})}),
    tool(()=>store.cancel(id),{name:"cancel_pending",description:"取消当前未提交的退款预览",schema:z.object({})})
  ];
}
