"""
快递单号注册脚本
用法：python scripts/register.py <快递单号> <飞书record_id> [KOL邮箱]

示例：
  python scripts/register.py SF1234567890 recXXXXXXXX kol@gmail.com

说明：
  - 快递单号：在飞书多维表格「物流单号」字段填好后，从记录 URL 或 API 获取 record_id
  - 飞书 record_id 格式：recXXXXXXXXXX
  - KOL 邮箱：填写后 17TRACK 会直接发状态通知邮件给 KOL（可选）
"""

import os
import sys
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()

TRACK17_KEY  = os.environ.get("TRACK17_KEY", "")
TRACK17_BASE = "https://api.17track.net/track/v2.2"


async def register(tracking_number: str, record_id: str, email: str = ""):
    body = {
        "number": tracking_number,
        "tag":    record_id,      # 关键：存飞书 record_id
        "email":  email,
        "auto_detection": True,
    }

    print(f"\n📦 注册快递单号：{tracking_number}")
    print(f"   飞书 record_id：{record_id}")
    if email:
        print(f"   KOL 邮箱：{email}")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{TRACK17_BASE}/register",
            headers={
                "17token": TRACK17_KEY,
                "Content-Type": "application/json",
            },
            json=[body],
        )
        data = resp.json()

    accepted = data.get("data", {}).get("accepted", [])
    rejected = data.get("data", {}).get("rejected", [])

    if accepted:
        carrier = accepted[0].get("carrier")
        print(f"\n✅ 注册成功！")
        print(f"   识别的物流商代码：{carrier}")
        print(f"   17TRACK 已开始追踪，Webhook 推送将在数分钟内到达")
    elif rejected:
        err = rejected[0].get("error", {})
        print(f"\n❌ 注册失败：{err.get('message')}")
        print(f"   错误代码：{err.get('code')}")
        if err.get("code") == -18019903:
            print("   提示：无法识别物流商，请手动指定 carrier 代码")
            print("   查询：https://res.17track.net/asset/carrier/info/apicarrier.all.json")
    else:
        print(f"\n⚠️  未知响应：{data}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法：python scripts/register.py <快递单号> <飞书record_id> [KOL邮箱]")
        sys.exit(1)

    tracking = sys.argv[1]
    rec_id   = sys.argv[2]
    email    = sys.argv[3] if len(sys.argv) > 3 else ""

    if not TRACK17_KEY:
        print("❌ 未设置 TRACK17_KEY 环境变量，请先复制 .env.example 为 .env 并填写")
        sys.exit(1)

    asyncio.run(register(tracking, rec_id, email))
