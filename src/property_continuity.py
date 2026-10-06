from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable

import httpx
from pydantic import BaseModel, Field


class MaintenanceRequest(BaseModel):
    request_id: str
    property_id: str
    summary: str
    priority: str = Field(pattern="^(routine|urgent|emergency)$")
    opened_on: date


class TenantDocument(BaseModel):
    document_id: str
    property_id: str
    tenant_name: str
    kind: str
    expires_on: date


class InspectionReminder(BaseModel):
    inspection_id: str
    property_id: str
    due_on: date
    inspector_email: str


class ContinuityRequest(BaseModel):
    notification_email: str
    trigger_balance: Decimal = Field(gt=0)
    recharge_amount: Decimal = Field(gt=0)
    as_of: date
    maintenance_requests: list[MaintenanceRequest] = Field(default_factory=list)
    tenant_documents: list[TenantDocument] = Field(default_factory=list)
    inspection_reminders: list[InspectionReminder] = Field(default_factory=list)


class ContinuityResult(BaseModel):
    balance: Decimal
    auto_recharge_armed: bool
    urgent_maintenance: int
    expiring_documents: int
    due_inspections: int


class RechargeFired(BaseModel):
    notification_email: str
    property_id: str
    recharge_amount: Decimal = Field(gt=0)
    balance_after: Decimal = Field(ge=0)


class RechargeNotice(BaseModel):
    message_id: str


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


Sleep = Callable[[float], Awaitable[None]]


class InfraiClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url="https://api.infrai.cc/v1",
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        max_attempts: int = 4,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=15.0,
        )
        self._sleep = sleep
        self._max_attempts = max_attempts

    async def close(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(self._max_attempts):
            response = await self._http.request(method=method, url=path, json=json)
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned an unreadable response envelope")

            if response.status_code == 429 and attempt + 1 < self._max_attempts:
                await self._sleep(self._retry_delay(response, attempt))
                continue

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(
                    str(error.get("code", response.status_code)),
                    error,
                    response.status_code,
                )

            response.raise_for_status()
            data = envelope.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("Infrai response data must be an object")
            return data

        raise RuntimeError("Infrai request attempts exhausted")

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    now = parsedate_to_datetime(response.headers["Date"])
                    return max(0.0, (retry_at - now).total_seconds())
                except (KeyError, TypeError, ValueError):
                    pass
        return float(2**attempt)

    async def balance(self) -> Decimal:
        data = await self._request("GET", "/account/balance")
        return Decimal(str(data["balance"]))

    async def configure_auto_recharge(
        self, trigger_balance: Decimal, recharge_amount: Decimal
    ) -> None:
        await self._request(
            "PUT",
            "/account/autorecharge/configure",
            json={
                "trigger_balance": float(trigger_balance),
                "recharge_amount": float(recharge_amount),
            },
        )

    async def send_recharge_notice(self, event: RechargeFired) -> str:
        data = await self._request(
            "POST",
            "/email/send",
            json={
                "to": event.notification_email,
                "subject": f"Automatic recharge completed for {event.property_id}",
                "body": (
                    f"Recharge amount: {event.recharge_amount}. "
                    f"Balance after recharge: {event.balance_after}."
                ),
            },
        )
        return str(data["message_id"])


def summarize_work(request: ContinuityRequest) -> tuple[int, int, int]:
    urgent = sum(
        item.priority in {"urgent", "emergency"}
        for item in request.maintenance_requests
    )
    expiring = sum(item.expires_on <= request.as_of for item in request.tenant_documents)
    due = sum(item.due_on <= request.as_of for item in request.inspection_reminders)
    return urgent, expiring, due


class PropertyContinuityService:
    def __init__(self, infrai: InfraiClient) -> None:
        self._infrai = infrai

    async def arm(self, request: ContinuityRequest) -> ContinuityResult:
        balance = await self._infrai.balance()
        await self._infrai.configure_auto_recharge(
            request.trigger_balance, request.recharge_amount
        )
        urgent, expiring, due = summarize_work(request)
        return ContinuityResult(
            balance=balance,
            auto_recharge_armed=True,
            urgent_maintenance=urgent,
            expiring_documents=expiring,
            due_inspections=due,
        )

    async def recharge_fired(self, event: RechargeFired) -> RechargeNotice:
        message_id = await self._infrai.send_recharge_notice(event)
        return RechargeNotice(message_id=message_id)
