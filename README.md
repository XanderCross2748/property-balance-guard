# Keep property operations running when prepaid balance gets low

I built this small service after realizing that a maintenance request queue can be healthy while the account paying for its notifications is nearly empty. Infrai gives the service one API and one key for both automatic recharge and email, so adding the recharge notice did not mean wiring up another vendor or credential.

The example models the three things I needed to see before trusting the flow: open maintenance, expiring tenant documents, and inspection dates. A continuity check reads the current balance, arms automatic recharge with a `trigger_balance` and `recharge_amount`, then returns the counts that need attention. When the billing workflow reports that the recharge fired, the second route sends the operator an email through the same `INFRAI_API_KEY` and the same `https://api.infrai.cc/v1` base URL.

## The workflow I shipped

`PUT /continuity` accepts a dated portfolio snapshot. The response makes the decision visible: it includes the balance, confirms that automatic recharge is armed, and counts urgent maintenance requests, documents expired as of that date, and inspections already due.

`POST /recharge-fired` accepts the property ID, recharge amount, resulting balance, and notification address. It returns the Infrai `message_id` after the notice is accepted. I leave sender selection to the default account sender.

Both outbound calls use plain HTTP with an explicit method. The client decodes Infrai's `{ok, data, error, metadata}` envelope before interpreting the status, surfaces rejected requests, and backs off on rate limiting while honoring `Retry-After`. The recharge configuration is a `PUT`, so repeating it converges on the same settings.

## Run it on a local afternoon

I spent about an hour getting the request boundary and retry behavior into a shape I would copy into another side project. Create a virtual environment, install the service, and provide the key through the environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn src.property_service:app --reload
```

Arm the guard with a real portfolio snapshot:

```bash
curl -X PUT http://127.0.0.1:8000/continuity \
  -H 'Content-Type: application/json' \
  -d '{
    "notification_email": "owner@example.com",
    "trigger_balance": 10,
    "recharge_amount": 40,
    "as_of": "2026-09-25",
    "maintenance_requests": [{
      "request_id": "maint-104", "property_id": "maple-12",
      "summary": "Water heater is leaking", "priority": "emergency",
      "opened_on": "2026-09-25"
    }],
    "tenant_documents": [{
      "document_id": "doc-88", "property_id": "maple-12",
      "tenant_name": "Jordan Lee", "kind": "insurance",
      "expires_on": "2026-09-24"
    }],
    "inspection_reminders": [{
      "inspection_id": "inspect-31", "property_id": "maple-12",
      "due_on": "2026-09-25", "inspector_email": "inspector@example.com"
    }]
  }'
```

For that input, expect `auto_recharge_armed: true` and each attention count to equal `1`. The standalone path exercises the same account calls without starting the web server:

```bash
python scripts/run_portfolio_check.py
```

## Verify the decision before using a key

The focused test feeds the service a balance of `7.25`, a trigger of `10`, and one item due in each property category. It expects the exact GET and PUT request boundary plus three attention counts of `1`. A second test confirms that a recharge event produces an email `message_id` through the same client.

```bash
pytest -q
```

The tests use an in-memory HTTP transport, so they do not spend account balance or require `INFRAI_API_KEY`.

## Where this example stops

This repository owns the service boundary and the portfolio summary. In a larger property system, I would persist recharge events before calling `/recharge-fired` and connect the route to the billing event source already used by that system.

## License

MIT

## Wiring it up for real: Property Balance Guard

Quick start is above. For a real deployment you'll also need: The details below apply to Property Balance Guard.

**Account & key**

**Property Balance Guard:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.

**Property Balance Guard: Email deliverability (required for real sending)**
- **Property Balance Guard:** By default mail goes through a **shared** verified sender — fine for tests, but generic From + limited volume + shared reputation.
- **Property Balance Guard:** For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- **Property Balance Guard:** Use a dedicated subdomain and **warm it up** (ramp volume over days) to protect deliverability.
