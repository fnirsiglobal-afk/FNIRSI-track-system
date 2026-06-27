"""
17TRACK Webhook 事件处理器
解析 TRACKING_UPDATED 推送 → 写入飞书多维表格
"""

import logging
from typing import Optional

from .feishu import (
    search_records_by_tracking,
    update_record,
    to_ms,
    now_ms,
)

log = logging.getLogger(__name__)

# 17TRACK 主状态 → 中文（飞书单选字段值）
MAIN_STATUS_MAP = {
    "NotFound":           "NotFound · 未找到",
    "InfoReceived":       "InfoReceived · 已揽件",
    "InTransit":          "InTransit · 运输中",
    "Expired":            "Expired · 超时未达",
    "AvailableForPickup": "AvailableForPickup · 待取件",
    "OutForDelivery":     "OutForDelivery · 派送中",
    "DeliveryFailure":    "DeliveryFailure · 投递失败",
    "Delivered":          "Delivered · 已签收",
    "Exception":          "Exception · 异常",
}


def _extract_milestone_times(events: list[dict]) -> dict:
    """
    从事件列表中提取里程碑时间
    - 揽收时间：sub_status == InTransit_PickedUp
    - 签收时间：sub_status == Delivered_Other
    """
    pickup_time = None
    delivered_time = None

    for evt in events:
        sub = evt.get("sub_status", "")
        t = evt.get("time_iso") or evt.get("time_utc")

        if sub == "InTransit_PickedUp" and pickup_time is None:
            pickup_time = to_ms(t)

        if sub == "Delivered_Other" and delivered_time is None:
            # 官方文档说签收时间在 time_raw 里
            raw = evt.get("time_raw") or t
            delivered_time = to_ms(raw)

    return {"pickup_time": pickup_time, "delivered_time": delivered_time}


def _extract_carrier_name(providers: list[dict]) -> Optional[str]:
    """从 providers 中提取运输商名称"""
    if not providers:
        return None
    p = providers[0]
    return p.get("provider", {}).get("name") or p.get("name")


async def process_single_tracking(tracking_data: dict):
    """
    处理单个包裹的推送数据 → 更新飞书记录
    tracking_data 是 data.accepted[] 中的单个对象
    """
    number = tracking_data.get("number")
    if not number:
        log.warning("No tracking number in payload, skipping")
        return

    tag = tracking_data.get("tag", "")  # 存的是飞书 record_id

    # 解析最新状态
    latest = tracking_data.get("latest_status", {})
    main_status = latest.get("status", "")
    sub_status = latest.get("sub_status", "")

    # 解析最新事件
    providers = tracking_data.get("tracking", {}).get("providers", [])
    latest_event = {}
    all_events = []
    if providers:
        all_events = providers[0].get("events", [])
        latest_event = all_events[0] if all_events else {}

    event_desc = latest_event.get("description", "")
    event_time = latest_event.get("time_iso") or latest_event.get("time_utc")
    carrier_name = _extract_carrier_name(providers)

    milestones = _extract_milestone_times(all_events)

    # 构造飞书字段
    fields = {
        "物流子状态":   sub_status or main_status,   # 单选，用 sub_status 更精确
        "子状态描述":   event_desc,                   # 文本
        "最新事件时间": to_ms(event_time),            # 日期（毫秒）
        "运输商":      carrier_name,                  # 单选
        "揽收时间":    milestones["pickup_time"],     # 日期（毫秒）
        "签收时间":    milestones["delivered_time"],  # 日期（毫秒）
        "最后推送时间": now_ms(),                     # 日期（毫秒）
    }

    # 定位飞书记录：优先用 tag（record_id），否则用单号搜索
    record_id = None
    if tag and tag.startswith("rec"):
        record_id = tag
        log.info(f"[{number}] Using tag as record_id: {record_id}")
    else:
        records = await search_records_by_tracking(number)
        if not records:
            log.warning(f"[{number}] No Feishu record found, skip update")
            return
        record_id = records[0]["record_id"]
        log.info(f"[{number}] Found record by search: {record_id}")

    ok = await update_record(record_id, fields)
    if ok:
        log.info(f"[{number}] Updated → sub_status={sub_status}")
    else:
        log.error(f"[{number}] Failed to update Feishu record")


async def process_webhook_payload(payload: dict):
    """
    处理完整的 Webhook payload
    支持 TRACKING_UPDATED 和 TRACKING_STOPPED 两种事件
    """
    event = payload.get("event")
    data = payload.get("data", {})

    log.info(f"Webhook event={event}")

    if event == "TRACKING_UPDATED":
        accepted = data.get("accepted", [])
        log.info(f"Processing {len(accepted)} tracking(s)")
        for item in accepted:
            try:
                await process_single_tracking(item)
            except Exception as e:
                log.error(f"Error processing {item.get('number')}: {e}")

    elif event == "TRACKING_STOPPED":
        accepted = data.get("accepted", [])
        for item in accepted:
            number = item.get("number", "")
            log.info(f"[{number}] Tracking stopped by 17TRACK")
            # 可在此更新飞书状态为「已停止跟踪」
            records = await search_records_by_tracking(number)
            if records:
                await update_record(
                    records[0]["record_id"],
                    {"物流子状态": "Stopped · 已停止跟踪", "最后推送时间": now_ms()},
                )
    else:
        log.warning(f"Unknown event type: {event}")
