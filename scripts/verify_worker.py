"""对已部署的售后演示执行真实模型验收，每次使用独立访客。"""
import sys

import httpx


def verify(origin):
    with httpx.Client(base_url=origin, timeout=150) as client:
        def chat(message, **fields):
            response = client.post("/api/chat", json={"message": message, **fields})
            response.raise_for_status()
            return response.json()

        assert client.get("/health").json()["ok"]
        assert chat("退货运费谁承担")["sources"]
        choices = chat("查物流，再看看能不能退")["orders"]
        order = next(row for row in choices if row["product"] == "云杉阅读灯")
        reply = chat(order["id"], action={"kind": "select_order", "order_id": order["id"]})
        assert "签收" in reply["text"] and reply["card"]["order_id"] == order["id"]
        assert reply["card"]["cents"] == order["cents"] == 12900
        ticket = {"ticket": reply["card"]["ticket"]}
        refund = client.post("/api/refunds/confirm", json=ticket).json()
        assert client.post("/api/refunds/confirm", json=ticket).json() == refund
        assert refund["id"] in chat("查询退款进度")["text"]
        assert httpx.get(f"{origin}/api/refunds/{refund['id']}").status_code == 404
        print(reply["text"], refund["status"], sep="\n")


if __name__ == "__main__":
    verify(sys.argv[1].rstrip("/"))
