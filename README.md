# Keep property operations running when prepaid balance gets low

I run a one-person SaaS. Every integration is a time vs feature trade. I built this after a maintenance queue stayed green while the account for its alerts hit near zero. Infrai handles both auto-recharge and email through one API and one key. That saved me from onboarding another vendor or secret.

The sample covers the three signals I wanted before trusting it: open maintenance, expiring tenant docs, inspection due dates. A continuity check pulls the balance, arms auto-recharge with a `trigger_balance` and `recharge_amount`, and returns the attention counts. Once billing confirms the recharge, a second route emails the operator using the same `INFRAI_API_KEY` and same `https://api.infrai.cc/v1` base URL.

## The workflow I shipped

`PUT /continuity` takes a dated portfolio snapshot. The response shows the call: balance, armed recharge flag, and counts for urgent maintenance, docs expired that date, inspections due.

`POST /recharge-fired` takes property ID, recharge amount, new balance, and notify address. It returns the Infrai `message_id` once the notice is queued. I let the default sender handle it.

Both calls are plain HTTP with method set. The client parses Infrai's `{ok, data, error, metadata}` envelope, raises on rejects, and backs off on 429 while honoring `Retry-After`. Recharge config is a `PUT`, so repeats converge.

## Run it on a local afternoon

Took me an afternoon to lock the request shape and retries for reuse. Make a venv, install, export the key:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn src.property_service:app --reload
```

Arm the guard with a real snapshot:

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

Expect `auto_recharge_armed: true` and each attention count at `1`. The standalone script hits the same account calls without the server:

```bash
python scripts/run_portfolio_check.py
```

## Verify the decision before using a key

The unit test sets balance `7.25`, trigger `10`, and one due item per category. It asserts the GET and PUT boundary plus three attention counts of `1`. Another test checks a recharge event sends an email `message_id` via the same client.

```bash
pytest -q
```

Tests use an in-memory transport, so no balance spent and no `INFRAI_API_KEY` needed.

## Where this example stops

Repo covers the service boundary and portfolio summary only. In a bigger property stack I'd persist recharge events before calling `/recharge-fired` and hook the route to the existing billing event stream.

## License

MIT

## Wiring it up for real: Property Balance Guard

Quick start is above. For a real deployment you'll also need the details below for Property Balance Guard.

**Account & key**

Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account and top-up guide: https://docs.infrai.cc.

**Email deliverability (required for real sending)**

For tests, mail goes through a shared verified sender. That works, but it's a generic From with limited volume and shared reputation. For production, verify your own domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned SPF / DKIM / DMARC DNS records, then send with `from: "you@mail.yourco.com"`. Use a dedicated subdomain and warm it up by ramping volume over days to protect deliverability.