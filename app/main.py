"""
17TRACK v2.4 → 飞书多维表格 包裹状态追踪服务
支持：
  1. 飞书按钮触发 Webhook → 注册单号 + 立即写入当前状态
  2. 17TRACK Webhook 推送 → 状态变更时自动更新飞书
  3. 定时轮询（可选） → 每天定时同步一次全表状态

字段映射（飞书字段名 → 17TRACK 数据）：
  物流单号        ← 你手动填入（触发查询的来源）
  物流子状态      ← latest_status.sub_status（单选）
  子状态描述      ← latest_status.sub_status_descr（文本）
  最新事件时间    ← latest_event.time_utc（日期）
  运输商          ← carrier name（单选，用 carrier code 推断）
  签收时间        ← delivered event time（日期）
  更新时间        ← 每次写入时的当前时间（日期）
"""

import os
import re
import hashlib
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ── 日志 ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 环境变量 ────────────────────────────────────────────────
TRACK17_API_KEY   = os.environ["TRACK17_API_KEY"]       # 17TRACK API Key
TRACK17_SECRET    = os.getenv("TRACK17_SECRET", "")     # 17TRACK Webhook 签名密钥（可选）

FEISHU_APP_ID     = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET = os.environ["FEISHU_APP_SECRET"]
BITABLE_APP_TOKEN = os.environ["BITABLE_APP_TOKEN"]     # /base/ 后面的字符串
BITABLE_TABLE_ID  = os.environ["BITABLE_TABLE_ID"]      # tbl 开头

# 字段名配置（如果你的飞书表格字段名不同，在这里改）
FIELD_TRACKING_NO    = os.getenv("FIELD_TRACKING_NO",    "物流单号")
FIELD_SUB_STATUS     = os.getenv("FIELD_SUB_STATUS",     "物流子状态")
FIELD_SUB_STATUS_DESC= os.getenv("FIELD_SUB_STATUS_DESC","子状态描述")
FIELD_LATEST_EVENT_T = os.getenv("FIELD_LATEST_EVENT_T", "最新事件时间")
FIELD_CARRIER        = os.getenv("FIELD_CARRIER",        "运输商")
FIELD_DELIVERED_TIME = os.getenv("FIELD_DELIVERED_TIME", "签收时间")
FIELD_UPDATE_TIME    = os.getenv("FIELD_UPDATE_TIME",    "更新时间")

# 定时任务
SCHEDULE_CRON = os.getenv("SCHEDULE_CRON", "0 8 * * *")   # 默认每天早8点
SCHEDULE_TZ   = os.getenv("SCHEDULE_TZ",   "Asia/Shanghai")

FS_BASE       = os.getenv("FEISHU_API_BASE", "https://open.feishu.cn") + "/open-apis"
TRACK17_BASE  = "https://api.17track.net/track/v2.4"

_refresh_lock = asyncio.Lock()

# ── 子状态中文映射（方便飞书单选字段显示） ─────────────────
SUB_STATUS_CN = {
    "NotFound_Other":                        "未找到",
    "NotFound_InvalidCode":                  "单号无效",
    "InfoReceived":                          "信息已收录",
    "InTransit_PickedUp":                    "已揽收",
    "InTransit_Other":                       "运输中",
    "InTransit_Departure":                   "已离港",
    "InTransit_Arrival":                     "已到港",
    "InTransit_CustomsProcessing":           "清关中",
    "InTransit_CustomsReleased":             "清关完成",
    "InTransit_CustomsRequiringInformation": "清关待资料",
    "Expired_Other":                         "已过期",
    "AvailableForPickup_Other":              "待自提",
    "OutForDelivery_Other":                  "派送中",
    "DeliveryFailure_Other":                 "派送失败",
    "DeliveryFailure_NoBody":                "无人签收",
    "DeliveryFailure_Security":              "安全/海关问题",
    "DeliveryFailure_Rejected":              "拒收",
    "DeliveryFailure_InvalidAddress":        "地址有误",
    "Delivered_Other":                       "已签收",
    "Exception_Other":                       "异常",
    "Exception_Returning":                   "退件中",
    "Exception_Returned":                    "已退件",
    "Exception_NoBody":                      "收件人异常",
    "Exception_Security":                    "安全/清关异常",
    "Exception_Damage":                      "包裹损坏",
    "Exception_Rejected":                    "已拒收",
    "Exception_Delayed":                     "延误",
    "Exception_Lost":                        "包裹丢失",
    "Exception_Destroyed":                   "包裹销毁",
    "Exception_Cancel":                      "已取消",
}

SUB_STATUS_DESC = {
    "NotFound_Other":                        "运输商没有返回信息。",
    "NotFound_InvalidCode":                  "物流单号无效，无法进行查询。",
    "InfoReceived":                          "收到信息，暂无细分含义与主状态一致。",
    "InTransit_PickedUp":                    "已揽收，运输商已从发件人处取回包裹。",
    "InTransit_Other":                       "其它情况，暂无细分除当前已知子状态之外的情况。",
    "InTransit_Departure":                   "已离港，货物离开起运地（国家/地区）港口。",
    "InTransit_Arrival":                     "已到港，货物到达目的地（国家/地区）港口。",
    "InTransit_CustomsProcessing":           "清关中，货物在海关办理进入或出口的相关流程中。",
    "InTransit_CustomsReleased":             "清关完成，货物在海关完成了进入或出口的流程。",
    "InTransit_CustomsRequiringInformation": "需要资料，在清关中流程中承运人需要提供相关资料才能完成清关。",
    "Expired_Other":                         "运输过久，暂无细分含义与主状态一致。",
    "AvailableForPickup_Other":              "到达待取，暂无细分含义与主状态一致。",
    "OutForDelivery_Other":                  "派送途中，暂无细分含义与主状态一致。",
    "DeliveryFailure_Other":                 "其它情况，暂无细分除当前已知子状态之外的情况。",
    "DeliveryFailure_NoBody":                "找不到收件人，派送中的包裹暂时无法联系上收件人，导致投递失败。",
    "DeliveryFailure_Security":              "安全原因，派送中发现的包裹安全、清关、费用问题，导致投递失败。",
    "DeliveryFailure_Rejected":              "拒收，收件人因某些原因拒绝接收包裹，导致投递失败。",
    "DeliveryFailure_InvalidAddress":        "地址错误，由于收件人地址不正确，导致投递失败。",
    "Delivered_Other":                       "成功签收，暂无细分含义与主状态一致。",
    "Exception_Other":                       "其它情况，暂无细分除当前已知子状态之外的情况。",
    "Exception_Returning":                   "退件中，包裹正在送回寄件人的途中。",
    "Exception_Returned":                    "退件签收，寄件人已成功收到退件。",
    "Exception_NoBody":                      "找不到收件人，在派送之前发现的收件人信息异常。",
    "Exception_Security":                    "安全原因，在派送之前发现异常，包含安全、清关、费用问题。",
    "Exception_Damage":                      "损坏，在承运过程中发现货物损坏了。",
    "Exception_Rejected":                    "拒收，在派送之前接收到有收件人拒收情况。",
    "Exception_Delayed":                     "延误，因各种情况导致的可能超出原定的运输周期。",
    "Exception_Lost":                        "丢失，因各种情况导致的货物丢失。",
    "Exception_Destroyed":                   "销毁，因各种情况无法完成交付的货物并进行销毁。",
    "Exception_Cancel":                      "取消，因为各种情况物流订单被取消了。",
}

# ══════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════

def iso_to_ts(iso: str) -> int | None:
    """ISO8601 字符串 → 毫秒时间戳（飞书日期字段）"""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def verify_17track_sign(raw_body: bytes, sign_header: str) -> bool:
    """验证 17TRACK Webhook 签名（TRACK17_SECRET 未设置时跳过验证）"""
    if not TRACK17_SECRET:
        return True
    expected = hashlib.sha256(
        raw_body + b"/" + TRACK17_SECRET.encode("utf-8")
    ).hexdigest()
    return expected == sign_header


def extract_track_fields(track_info: dict) -> dict:
    """
    从 17TRACK Webhook / gettrackinfo 返回的 track_info 对象中
    提取需要写入飞书的字段。
    """
    latest_status = track_info.get("latest_status") or {}
    latest_event  = track_info.get("latest_event")  or {}
    time_metrics  = track_info.get("time_metrics")  or {}

    sub_status      = latest_status.get("sub_status") or ""
    sub_status_desc = SUB_STATUS_DESC.get(sub_status, "") if sub_status else ""

    latest_event_time = iso_to_ts(latest_event.get("time_utc"))

    # 签收时间：遍历事件找 Delivered_Other 的 time_utc
    delivered_time = None
    providers = track_info.get("tracking", {}).get("providers") or []
    for provider in providers:
        for event in (provider.get("events") or []):
            if event.get("sub_status") == "Delivered_Other":
                delivered_time = iso_to_ts(event.get("time_utc"))
                break
        if delivered_time:
            break

    # 运输商名称：取第一个 provider 的名称
    carrier_name = ""
    if providers:
        carrier_name = providers[0].get("provider", {}).get("name", "") or ""
    if not carrier_name:
        carrier_name = "其他"

    is_delivered = (latest_status.get("status") == "Delivered")

    fields = {
        FIELD_SUB_STATUS:      SUB_STATUS_CN.get(sub_status, sub_status) or None,
        FIELD_SUB_STATUS_DESC: sub_status_desc or None,
        FIELD_LATEST_EVENT_T:  latest_event_time,
        FIELD_CARRIER:         carrier_name,
        FIELD_DELIVERED_TIME:  delivered_time,
        FIELD_UPDATE_TIME:     now_ts(),
    }
    # 过滤 None
    return {k: v for k, v in fields.items() if v is not None}, is_delivered


# ══════════════════════════════════════════════════════════════
#  17TRACK API
# ══════════════════════════════════════════════════════════════

async def track17_register(client: httpx.AsyncClient, tracking_numbers: list[str]) -> dict:
    """注册单号到 17TRACK（最多 40 个/次）"""
    payload = [{"number": n, "auto_detection": True} for n in tracking_numbers]
    r = await client.post(
        f"{TRACK17_BASE}/register",
        headers={"17token": TRACK17_API_KEY, "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    return r.json()


async def track17_stoptrack(client: httpx.AsyncClient, tracking_numbers: list[str]):
    """停止追踪已签收的单号，节省配额"""
    payload = [{"number": n} for n in tracking_numbers]
    try:
        r = await client.post(
            f"{TRACK17_BASE}/stoptrack",
            headers={"17token": TRACK17_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        logger.info(f"停止追踪 {tracking_numbers}: {r.json().get('code')}")
    except Exception as e:
        logger.warning(f"停止追踪失败（不影响主流程）: {e}")


async def track17_gettrackinfo(client: httpx.AsyncClient, tracking_numbers: list[dict]) -> dict:
    """
    主动拉取物流信息（gettrackinfo）
    tracking_numbers: [{"number": "...", "carrier": 0}, ...]
    """
    r = await client.post(
        f"{TRACK17_BASE}/gettrackinfo",
        headers={"17token": TRACK17_API_KEY, "Content-Type": "application/json"},
        json=tracking_numbers,
        timeout=30,
    )
    return r.json()


# ══════════════════════════════════════════════════════════════
#  飞书 API
# ══════════════════════════════════════════════════════════════

async def get_feishu_token(client: httpx.AsyncClient) -> str:
    r = await client.post(
        f"{FS_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=10,
    )
    data = r.json()
    token = data.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"飞书鉴权失败: {data}")
    return token


async def update_record(client: httpx.AsyncClient, token: str,
                        record_id: str, fields: dict):
    url = (f"{FS_BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}"
           f"/tables/{BITABLE_TABLE_ID}/records/{record_id}")
    r = await client.put(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"fields": fields},
        timeout=20,
    )
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"飞书写入失败 HTTP {r.status_code}: {r.text[:200]}")
    if data.get("code") != 0:
        raise RuntimeError(f"飞书写入失败 code={data.get('code')} msg={data.get('msg')}")
    return data


async def list_all_records(client: httpx.AsyncClient, token: str,
                          skip_delivered: bool = True) -> list:
    """拉取全部有「物流单号」字段的记录（自动翻页）。
    skip_delivered=True 时跳过已签收的行（默认开启，用于定时刷新）。
    """
    records = []
    page_token = None
    field_names = f'["{FIELD_TRACKING_NO}", "{FIELD_SUB_STATUS}"]'
    while True:
        params = {"page_size": 100, "field_names": field_names}
        if page_token:
            params["page_token"] = page_token
        url = (f"{FS_BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}"
               f"/tables/{BITABLE_TABLE_ID}/records")
        r = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=20,
        )
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"拉取记录失败: {data.get('msg')}")
        for item in data.get("data", {}).get("items", []):
            fields = item.get("fields", {})
            no_field = fields.get(FIELD_TRACKING_NO, "")
            no = (no_field.strip() if isinstance(no_field, str)
                  else (no_field or {}).get("text", "").strip())
            if not no:
                continue
            # 飞书单选字段值可能是字符串或 {"text": "..."} 对象
            sub_status_raw = fields.get(FIELD_SUB_STATUS, "")
            sub_status_val = (sub_status_raw if isinstance(sub_status_raw, str)
                              else (sub_status_raw or {}).get("text", ""))
            if skip_delivered and sub_status_val in ("已签收",):
                logger.debug(f"跳过已签收: {no}")
                continue
            records.append({"record_id": item["record_id"], "tracking_no": no})
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token")
    return records


async def find_record_by_tracking_no(client: httpx.AsyncClient, token: str,
                                     tracking_no: str) -> str | None:
    """根据单号在飞书表格里找到对应的 record_id"""
    records = await list_all_records(client, token)
    for rec in records:
        if rec["tracking_no"].upper() == tracking_no.upper():
            return rec["record_id"]
    return None


# ══════════════════════════════════════════════════════════════
#  定时任务：全表刷新
# ══════════════════════════════════════════════════════════════

async def refresh_all_records():
    """拉取飞书全部单号 → 批量查询 17TRACK → 写回飞书"""
    if _refresh_lock.locked():
        logger.warning("定时任务：上一轮未完成，跳过")
        return

    async with _refresh_lock:
        logger.info("═══ 定时刷新开始 ═══")
        start = datetime.now()
        async with httpx.AsyncClient() as client:
            try:
                token = await get_feishu_token(client)
                records = await list_all_records(client, token)
            except Exception as e:
                logger.error(f"定时任务初始化失败: {e}")
                return

            logger.info(f"共 {len(records)} 条记录")
            ok = fail = 0

            # 每次最多 40 个提交给 17TRACK
            batch_size = 40
            for i in range(0, len(records), batch_size):
                batch = records[i: i + batch_size]
                payload = [{"number": r["tracking_no"]} for r in batch]

                try:
                    resp = await track17_gettrackinfo(client, payload)
                except Exception as e:
                    logger.error(f"17TRACK 查询失败: {e}")
                    fail += len(batch)
                    continue

                accepted = resp.get("data", {}).get("accepted", [])
                # 建立单号 → track_info 索引
                info_map = {item["number"].upper(): item.get("track_info", {})
                            for item in accepted}

                # 刷新 token（批量多时可能超 2 小时）
                if i > 0 and i % 200 == 0:
                    token = await get_feishu_token(client)

                for rec in batch:
                    ti = info_map.get(rec["tracking_no"].upper())
                    if not ti:
                        logger.warning(f"  17TRACK 未返回数据: {rec['tracking_no']}")
                        fail += 1
                        continue
                    try:
                        fields, is_delivered = extract_track_fields(ti)
                        await update_record(client, token, rec["record_id"], fields)
                        logger.info(f"  ✓ {rec['tracking_no']}")
                        ok += 1
                        if is_delivered:
                            logger.info(f"  已签收，停止追踪: {rec['tracking_no']}")
                            await track17_stoptrack(client, [rec["tracking_no"]])
                    except Exception as e:
                        logger.error(f"  ✗ {rec['tracking_no']} → {e}")
                        fail += 1

                await asyncio.sleep(0.5)   # 避免触发限速

        elapsed = (datetime.now() - start).seconds
        logger.info(f"═══ 刷新完成：✓{ok} ✗{fail} 耗时{elapsed}s ═══")


# ══════════════════════════════════════════════════════════════
#  FastAPI 应用
# ══════════════════════════════════════════════════════════════

scheduler = AsyncIOScheduler(timezone=SCHEDULE_TZ)


@asynccontextmanager
async def lifespan(app: FastAPI):
    parts = SCHEDULE_CRON.strip().split()
    if len(parts) == 5:
        minute, hour, day, month, dow = parts
        scheduler.add_job(
            refresh_all_records,
            CronTrigger(minute=minute, hour=hour, day=day,
                        month=month, day_of_week=dow, timezone=SCHEDULE_TZ),
            id="refresh_all", replace_existing=True, misfire_grace_time=300,
        )
        scheduler.start()
        logger.info(f"✅ 定时任务已启动 Cron={SCHEDULE_CRON} TZ={SCHEDULE_TZ}")
    else:
        logger.error(f"SCHEDULE_CRON 格式错误: {SCHEDULE_CRON}，定时任务未启动")
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="17TRACK → 飞书多维表格 包裹追踪服务", lifespan=lifespan)


# ══════════════════════════════════════════════════════════════
#  路由
# ══════════════════════════════════════════════════════════════

@app.post("/webhook/feishu")
async def webhook_feishu(request: Request):
    """
    飞书按钮触发入口。
    飞书 POST 的 JSON：
      { "record_id": "recXXX", "tracking_no": "单号文本" }
    流程：注册到 17TRACK → 立即主动拉一次信息 → 写入飞书
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "请求体必须是 JSON")

    record_id   = (body.get("record_id") or "").strip()
    tracking_no = (body.get("tracking_no") or "").strip()

    if not record_id:
        raise HTTPException(400, "缺少 record_id")
    if not tracking_no:
        raise HTTPException(400, "缺少 tracking_no（物流单号字段为空）")

    logger.info(f"飞书触发: record={record_id} no={tracking_no}")

    async def _process():
        async with httpx.AsyncClient() as client:
            # Step 1：注册单号（已注册的会被 rejected，忽略）
            try:
                await track17_register(client, [tracking_no])
            except Exception as e:
                logger.warning(f"注册单号失败（可能已注册）: {e}")

            # Step 2：主动拉取最新物流信息
            try:
                resp = await track17_gettrackinfo(client, [{"number": tracking_no}])
            except Exception as e:
                logger.error(f"17TRACK 查询失败: {e}")
                return

            accepted = resp.get("data", {}).get("accepted", [])
            if not accepted:
                logger.warning(f"17TRACK 暂无数据: {tracking_no}")
                return

            track_info = accepted[0].get("track_info") or {}
            fields, is_delivered = extract_track_fields(track_info)
            if not fields:
                logger.warning(f"无有效字段可写入: {tracking_no}")
                return

            # Step 3：写入飞书
            try:
                fs_token = await get_feishu_token(client)
                await update_record(client, fs_token, record_id, fields)
                logger.info(f"飞书写入成功: {tracking_no}")
            except Exception as e:
                logger.error(f"飞书写入失败: {e}")
                return

            # Step 4：已签收则停止 17TRACK 追踪
            if is_delivered:
                logger.info(f"已签收，停止追踪: {tracking_no}")
                await track17_stoptrack(client, [tracking_no])

    # 立即返回 200，后台执行（避免飞书 webhook 超时）
    asyncio.create_task(_process())
    return JSONResponse({"code": 0, "msg": "processing"})


@app.post("/webhook/17track")
async def webhook_17track(request: Request):
    """
    17TRACK 推送入口。
    每当包裹状态变更，17TRACK 会 POST 到这里。
    系统根据 tag（飞书 record_id）定位到对应行并更新。
    """
    raw_body = await request.body()
    sign     = request.headers.get("sign", "")

    if not verify_17track_sign(raw_body, sign):
        logger.warning("17TRACK 签名验证失败")
        raise HTTPException(400, "签名验证失败")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "JSON 解析失败")

    event = data.get("event", "")
    if event != "TRACKING_UPDATED":
        # TRACKING_STOPPED 等其他事件直接忽略，返回 200 防止重推
        return JSONResponse({"code": 0, "msg": "ignored"})

    accepted = data.get("data", {}).get("accepted", [])
    logger.info(f"17TRACK 推送: {len(accepted)} 条")

    async def _process_push():
        async with httpx.AsyncClient() as client:
            try:
                fs_token = await get_feishu_token(client)
            except Exception as e:
                logger.error(f"飞书鉴权失败: {e}")
                return

            for item in accepted:
                tracking_no = item.get("number", "")
                tag         = item.get("tag", "")   # 注册时传入的 record_id
                track_info  = item.get("track_info") or {}

                # 优先用 tag 作为 record_id；没有则到飞书搜索
                record_id = tag if tag.startswith("rec") else None
                if not record_id:
                    try:
                        record_id = await find_record_by_tracking_no(
                            client, fs_token, tracking_no)
                    except Exception as e:
                        logger.error(f"查找 record_id 失败 {tracking_no}: {e}")
                        continue
                if not record_id:
                    logger.warning(f"未找到 record_id: {tracking_no}")
                    continue

                fields, is_delivered = extract_track_fields(track_info)
                if not fields:
                    continue
                try:
                    await update_record(client, fs_token, record_id, fields)
                    logger.info(f"推送写入成功: {tracking_no}")
                except Exception as e:
                    logger.error(f"推送写入失败 {tracking_no}: {e}")
                    continue

                if is_delivered:
                    logger.info(f"已签收，停止追踪: {tracking_no}")
                    await track17_stoptrack(client, [tracking_no])

    asyncio.create_task(_process_push())
    return JSONResponse({"code": 0, "msg": "received"})


@app.post("/admin/refresh-now")
async def trigger_refresh():
    """手动触发全表刷新"""
    if _refresh_lock.locked():
        return JSONResponse({"code": 1, "msg": "上一轮仍在执行"})
    asyncio.create_task(refresh_all_records())
    return JSONResponse({"code": 0, "msg": "已在后台启动"})


@app.get("/admin/status")
async def status():
    """查看定时任务状态"""
    jobs = []
    for job in scheduler.get_jobs():
        nr = job.next_run_time
        jobs.append({"id": job.id, "next_run": nr.isoformat() if nr else None})
    return JSONResponse({
        "scheduler_running": scheduler.running,
        "cron": SCHEDULE_CRON,
        "timezone": SCHEDULE_TZ,
        "jobs": jobs,
        "refresh_running": _refresh_lock.locked(),
    })


@app.get("/admin/debug-records")
async def debug_records():
    """列出表格前 5 条记录，验证字段名和 record_id 是否正确"""
    async with httpx.AsyncClient() as client:
        token = await get_feishu_token(client)
        url = (f"{FS_BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}"
               f"/tables/{BITABLE_TABLE_ID}/records?page_size=5")
        r = await client.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        try:
            data = r.json()
        except Exception:
            return JSONResponse({"error": f"HTTP {r.status_code}", "body": r.text[:300]})
        items = data.get("data", {}).get("items", [])
        return JSONResponse({
            "records": [
                {"record_id": i.get("record_id"),
                 FIELD_TRACKING_NO: i.get("fields", {}).get(FIELD_TRACKING_NO)}
                for i in items
            ]
        })


@app.get("/health")
async def health():
    return {"status": "ok"}
