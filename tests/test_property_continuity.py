from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from decimal import Decimal

import httpx

from src.property_continuity import (
    ContinuityRequest,
    InfraiClient,
    InspectionReminder,
    MaintenanceRequest,
    PropertyContinuityService,
    RechargeFired,
    TenantDocument,
)


def test_arms_recharge_and_counts_work_that_needs_attention() -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, payload))
        if request.url.path.endswith("/account/balance"):
            return httpx.Response(200, json={"ok": True, "data": {"balance": "7.25"}})
        return httpx.Response(200, json={"ok": True, "data": {"enabled": True}})

    today = date(2026, 9, 25)
    request = ContinuityRequest(
        notification_email="owner@example.com",
        trigger_balance=Decimal("10"),
        recharge_amount=Decimal("40"),
        as_of=today,
        maintenance_requests=[
            MaintenanceRequest(
                request_id="m-1",
                property_id="oak-4",
                summary="No hot water",
                priority="emergency",
                opened_on=today,
            ),
            MaintenanceRequest(
                request_id="m-2",
                property_id="oak-4",
                summary="Loose cabinet handle",
                priority="routine",
                opened_on=today,
            ),
        ],
        tenant_documents=[
            TenantDocument(
                document_id="d-1",
                property_id="oak-4",
                tenant_name="Sam",
                kind="insurance",
                expires_on=today,
            )
        ],
        inspection_reminders=[
            InspectionReminder(
                inspection_id="i-1",
                property_id="oak-4",
                due_on=today - timedelta(days=1),
                inspector_email="inspector@example.com",
            )
        ],
    )
    client = InfraiClient("test-key", transport=httpx.MockTransport(handler))

    async def scenario() -> None:
        result = await PropertyContinuityService(client).arm(request)
        assert result.balance == Decimal("7.25")
        assert result.auto_recharge_armed is True
        assert result.urgent_maintenance == 1
        assert result.expiring_documents == 1
        assert result.due_inspections == 1
        assert calls == [
            ("GET", "/v1/account/balance", None),
            (
                "PUT",
                "/v1/account/autorecharge/configure",
                {"trigger_balance": 10.0, "recharge_amount": 40.0},
            ),
        ]
        await client.close()

    asyncio.run(scenario())


def test_recharge_event_sends_notice_with_the_same_client() -> None:
    authorization_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization_headers.append(request.headers["Authorization"])
        assert request.method == "POST"
        assert request.url.path == "/v1/email/send"
        payload = json.loads(request.content)
        assert payload["to"] == "owner@example.com"
        assert "from" not in payload
        return httpx.Response(200, json={"ok": True, "data": {"message_id": "msg-42"}})

    client = InfraiClient("shared-test-key", transport=httpx.MockTransport(handler))

    async def scenario() -> None:
        notice = await PropertyContinuityService(client).recharge_fired(
            RechargeFired(
                notification_email="owner@example.com",
                property_id="oak-4",
                recharge_amount=Decimal("40"),
                balance_after=Decimal("47.25"),
            )
        )
        assert notice.message_id == "msg-42"
        assert authorization_headers == ["Bearer shared-test-key"]
        await client.close()

    asyncio.run(scenario())

