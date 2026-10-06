from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from decimal import Decimal

from src.property_continuity import (
    ContinuityRequest,
    InfraiClient,
    InspectionReminder,
    MaintenanceRequest,
    PropertyContinuityService,
    TenantDocument,
)


async def main() -> None:
    api_key = os.environ.get("INFRAI_API_KEY")
    if not api_key:
        raise SystemExit("Set INFRAI_API_KEY before running this check")

    today = date.today()
    request = ContinuityRequest(
        notification_email="operator@example.com",
        trigger_balance=Decimal("10"),
        recharge_amount=Decimal("50"),
        as_of=today,
        maintenance_requests=[
            MaintenanceRequest(
                request_id="maint-104",
                property_id="maple-12",
                summary="Water heater is leaking",
                priority="emergency",
                opened_on=today,
            )
        ],
        tenant_documents=[
            TenantDocument(
                document_id="doc-88",
                property_id="maple-12",
                tenant_name="Jordan Lee",
                kind="insurance",
                expires_on=today - timedelta(days=1),
            )
        ],
        inspection_reminders=[
            InspectionReminder(
                inspection_id="inspect-31",
                property_id="maple-12",
                due_on=today,
                inspector_email="inspector@example.com",
            )
        ],
    )

    client = InfraiClient(api_key)
    try:
        result = await PropertyContinuityService(client).arm(request)
        print(result.model_dump_json(indent=2))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

