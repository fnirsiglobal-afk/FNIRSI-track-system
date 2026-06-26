from fastapi import FastAPI, Request
from feishu import update_feishu

app = FastAPI()

@app.post("/webhook/17track")
async def track_webhook(req: Request):
    data = await req.json()

    event = {
        "tracking_number": data.get("tracking_number"),
        "carrier": data.get("carrier"),
        "sub_status": data.get("sub_status"),
        "sub_status_desc": data.get("sub_status_desc"),
        "event_time": data.get("time"),
        "status": data.get("status"),
    }

    await update_feishu(event)

    return {"ok": True}
