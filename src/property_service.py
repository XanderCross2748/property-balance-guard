from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .property_continuity import (
    ContinuityRequest,
    ContinuityResult,
    InfraiClient,
    InfraiError,
    PropertyContinuityService,
    RechargeFired,
    RechargeNotice,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    api_key = os.environ.get("INFRAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set INFRAI_API_KEY before starting the service")
    client = InfraiClient(api_key)
    app.state.continuity = PropertyContinuityService(client)
    yield
    await client.close()


app = FastAPI(title="Property Balance Guard", lifespan=lifespan)


@app.exception_handler(InfraiError)
async def infrai_error_handler(_: Request, exc: InfraiError) -> JSONResponse:
    status_code = exc.status_code if 400 <= exc.status_code < 500 else 502
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": {
                "code": exc.code,
                "message": exc.detail.get("message", exc.code),
            }
        },
    )


@app.put("/continuity", response_model=ContinuityResult)
async def arm_continuity(request: Request, body: ContinuityRequest) -> ContinuityResult:
    service: PropertyContinuityService = request.app.state.continuity
    return await service.arm(body)


@app.post("/recharge-fired", response_model=RechargeNotice)
async def recharge_fired(request: Request, body: RechargeFired) -> RechargeNotice:
    service: PropertyContinuityService = request.app.state.continuity
    return await service.recharge_fired(body)
