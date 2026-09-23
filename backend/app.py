import asyncio
import hashlib
import hmac
import json
import os
import time
from collections import OrderedDict, deque
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from contracts import Snapshot
from deepseek_client import propose, ModelFailure
from recon_transfer import router as reconstruction_router

app = FastAPI(title="SELF private candidate planner", docs_url=None, redoc_url=None)
app.include_router(reconstruction_router)
recent = deque()
completed = OrderedDict()
inflight: set[str] = set()

@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Pydantic error input may contain an image or personal utterance: never echo it.
    return JSONResponse(status_code=422, content={"error": "invalid_request"})

@app.get("/health")
async def health():
    return {"status": "ready", "modelConfigured": bool(os.getenv("DEEPSEEK_API_KEY"))}

@app.post("/v1/edit-plans")
async def edit_plans(request: Request):
    token = os.getenv("SELF_BACKEND_TOKEN", "")
    if token:
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            raise HTTPException(401, "unauthorized")
    elif not (os.getenv("SELF_DEV_LOOPBACK") == "1" and request.client and request.client.host in {"127.0.0.1", "::1", "testclient"}):
        raise HTTPException(503, "backend_auth_not_configured")
    now = time.monotonic()
    while recent and now-recent[0] > 60:
        recent.popleft()
    if len(recent) >= 12 or len(inflight) >= 2:
        raise HTTPException(429, "rate_limit")
    try:
        length = int(request.headers.get("content-length", "0"))
        if length < 0: raise ValueError()
    except ValueError:
        raise HTTPException(400, "invalid_content_length") from None
    if length > 11*1024*1024:
        raise HTTPException(413, "request_size")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 11*1024*1024:
            raise HTTPException(413, "request_size")
    try:
        # Narrow JSON wire contract; PNG is an image field, never model text. No multipart temp files.
        import base64
        body = json.loads(data)
        if set(body) != {"snapshot", "images"}:
            raise ValueError()
        snapshot = Snapshot.model_validate(body["snapshot"])
        if not 1 <= len(body["images"]) <= 2:
            raise ValueError()
        images = [base64.b64decode(encoded, validate=True) for encoded in body["images"]]
    except Exception:
        raise HTTPException(422, "invalid_request") from None
    key = snapshot.requestId
    digest = hashlib.sha256(data).hexdigest()
    if key in completed:
        old_digest, result = completed[key]
        if digest != old_digest:
            raise HTTPException(409, "request_id_reused")
        return result
    if key in inflight:
        raise HTTPException(409, "request_in_progress")
    recent.append(now)
    inflight.add(key)
    task = asyncio.create_task(propose(snapshot, images))
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=.2)
            if await request.is_disconnected():
                task.cancel()
                raise HTTPException(499, "client_cancelled")
        result = await task
        completed[key] = (digest, result)
        while len(completed) > 64:
            completed.popitem(last=False)
        return result
    except ModelFailure as error:
        raise HTTPException(502, str(error)) from None
    finally:
        if not task.done():
            task.cancel()
        inflight.discard(key)
