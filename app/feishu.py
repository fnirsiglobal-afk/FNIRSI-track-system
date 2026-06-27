"""
飞书多维表格 API 客户端
- tenant_access_token 自动刷新
- 查询 / 更新记录
- 日期字段转毫秒时间戳
"""

import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

log = logging.getLogger(__name__)

FEISHU_APP_ID     = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET = os.environ["FEISHU_APP_SECRET"]
FEISHU_APP_TOKEN  = os.environ["FEISHU_APP_TOKEN"]   # 多维表格 app_token
FEISHU_TABLE_ID   = os.environ["FEISHU_TABLE_ID"]    # 数据表 table_id

FEISHU_BASE = "https://open.feishu.cn/open-apis"

# ── Token 缓存 ────────────────────────────────────────────────────
_token_cache: dict = {"token": "", "expires_at": 0}


async def get_token() -> str:
    """获取 tenant_access_token，有效期内复用"""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"Feishu token error: {data}")

    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = now + data.get("expire", 7200)
    log.info("Feishu token refreshed")
    return _token_cache["token"]


# ── 工具函数 ──────────────────────────────────────────────────────
def to_ms(dt_str: Optional[str]) -> Optional[int]:
    """
    ISO 8601 / 常见格式字符串 → 毫秒时间戳（飞书日期字段格式）
    返回 None 表示无法解析
    """
    if not dt_str:
        return None
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(dt_str.strip(), fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    log.warning(f"Cannot parse date: {dt_str!r}")
    return None


def now_ms() -> int:
    return int(time.time() * 1000)


# ── 记录操作 ──────────────────────────────────────────────────────
async def search_records_by_tracking(tracking_number: str) -> list[dict]:
    """
    用快递单号搜索飞书记录
    返回匹配的记录列表（通常只有一条）
    """
    token = await get_token()
    url = (
        f"{FEISHU_BASE}/bitable/v1/apps/{FEISHU_APP_TOKEN}"
        f"/tables/{FEISHU_TABLE_ID}/records/search"
    )
    body = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {
                    "field_name": "物流单号",
                    "operator": "is",
                    "value": [tracking_number],
                }
            ],
        }
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 0:
        log.error(f"search_records error: {data}")
        return []

    return data.get("data", {}).get("items", [])


async def update_record(record_id: str, fields: dict) -> bool:
    """
    PUT 更新飞书多维表格指定记录
    fields: {字段名: 值}，日期字段传毫秒整数
    """
    token = await get_token()
    url = (
        f"{FEISHU_BASE}/bitable/v1/apps/{FEISHU_APP_TOKEN}"
        f"/tables/{FEISHU_TABLE_ID}/records/{record_id}"
    )
    # 过滤掉 None 值，避免覆盖已有数据
    clean_fields = {k: v for k, v in fields.items() if v is not None}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"fields": clean_fields},
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 0:
        log.error(f"update_record {record_id} error: {data}")
        return False

    log.info(f"update_record {record_id} OK: {list(clean_fields.keys())}")
    return True


async def search_records_needing_poll(hours: int = 48) -> list[dict]:
    """
    查找超过 N 小时未收到 Webhook 推送且状态仍在途的记录
    用于 Polling 兜底
    """
    import time
    token = await get_token()
    url = (
        f"{FEISHU_BASE}/bitable/v1/apps/{FEISHU_APP_TOKEN}"
        f"/tables/{FEISHU_TABLE_ID}/records/search"
    )
    cutoff_ms = int((time.time() - hours * 3600) * 1000)

    # 筛选条件：物流子状态不是「Delivered」且最后推送时间早于截止点
    body = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {
                    "field_name": "物流子状态",
                    "operator": "isNot",
                    "value": ["Delivered"],
                },
                {
                    "field_name": "最后推送时间",
                    "operator": "isLessThan",
                    "value": [str(cutoff_ms)],
                },
            ],
        },
        "field_names": ["物流单号", "record_id"],
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 0:
        log.error(f"search_records_needing_poll error: {data}")
        return []

    items = data.get("data", {}).get("items", [])
    result = []
    for item in items:
        fields = item.get("fields", {})
        tracking_number = fields.get("物流单号", "")
        if tracking_number:
            result.append({
                "record_id": item["record_id"],
                "tracking_number": tracking_number,
            })
    return result
