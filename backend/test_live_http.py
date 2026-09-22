"""Explicit paid local-backend probe; sends only an original synthetic fixture."""
import asyncio
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import deepseek_client  # Loads the private .env; never print configuration values.
from test_contracts import snapshot


async def main():
    folder = Path(__file__).resolve().parents[1] / "docs/evidence/deepseek"
    s = snapshot()
    s.requestId = "http-live-" + str(int(datetime.now().timestamp()))
    s.snapshotId = s.requestId
    s.imageWidth = s.imageHeight = 768
    s.userText = "请描述图片中图形的颜色、形状和数量，并为已登记 lip 区域新增 rose 轻度数字试色候选。"
    payload = {"snapshot": s.model_dump(), "images": [base64.b64encode((folder / "red-circle.png").read_bytes()).decode("ascii")]}
    token = os.getenv("SELF_BACKEND_TOKEN", "")
    headers = {"Authorization": "Bearer " + token} if token else {}
    result = {"testedAt": datetime.now(timezone.utc).isoformat(), "source": "Host HTTP -> running SELF backend -> real DeepSeek. Original red-circle fixture only. This is not a phone UI test."}
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        health = await client.get("http://127.0.0.1:8787/health")
        result["health"] = health.json()
        first = await client.post("http://127.0.0.1:8787/v1/edit-plans", json=payload, headers=headers)
        result["httpStatus"] = first.status_code
        if first.status_code == 200:
            data = first.json()
            result["result"] = data
            second = await client.post("http://127.0.0.1:8787/v1/edit-plans", json=payload, headers=headers)
            result["idempotentReplayMatched"] = second.status_code == 200 and second.json() == data
            message = data["plan"]["shortMessage"]
            ops = data["plan"]["operations"]
            result["visualDescriptionMatched"] = "红" in message and "圆" in message and ("1" in message or "一" in message)
            result["toolSelectionMatched"] = len(ops) == 1 and ops[0]["operation"] == "set_digital_tint" and ops[0]["presetId"] == "rose" and ops[0]["intensityLevel"] == "light"
            result["status"] = "passed" if all(result[k] for k in ("idempotentReplayMatched", "visualDescriptionMatched", "toolSelectionMatched")) else "failed"
        else:
            result["status"] = "failed"
            result["error"] = first.json()  # Backend errors contain categories only.
    (folder / "live-http-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
