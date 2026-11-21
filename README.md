# Exin Lab Ops

Procurement, customs clearance, and inventory for a research lab.
FastAPI + SQLite + a buildless vanilla ES-module SPA. No npm, no bundler,
no CDN.

## Run

```bash
pip install -r requirements.txt
python run.py
```

Open http://localhost:8770 and press **1-click demo login** (admin), or sign in as
`member` / `viewer` with the passwords shown on the login card.

`HOST` (default `0.0.0.0`) and `PORT` (default `8770`) come from the environment,
so the same command works locally and on Render / Railway / Fly. Set
`COOKIE_SECURE=1` on any HTTPS deployment.

The first boot creates `bgc_lab.db`, applies the schema, seeds the demo lab, and
starts one Uvicorn worker. Delete the file to start over.

## What is in the demo

- 6 common molecular-biology reagents with burn rates, safety stock and lead
  times (4 already low).
- Competing quotes for the phospho-tau antibody: local PH distributor, US direct,
  and Alibaba — each priced to a PHP landed cost including freight, dry ice, BOC
  duty and 12% VAT.
- One lot 18 days from expiry (B-27 supplement).
- One import PO sitting in `at_boc_filing`, last followed up 3 days ago, so the
  48-hour watchdog is red on first boot.

## The three workflows

1. **Quotes** — pick an item, compare landed cost and bench lead time, then
   *Award → PO*. The award runs in one transaction: chosen quote becomes
   `primary`, the cheapest rival becomes `backup`, and the PO is created.
2. **Customs** — move an order through the PH clearance stages, tick the four
   import documents, set the permit (NONE/FDA/PDEA/DENR), and chase anything the
   broker has gone quiet on. *Log follow-up* clears the badge.
3. **Receiving** — receiving requires the vendor lot number, expiry, cold-chain
   status and storage location before a lot is minted and stock increments.
   Short shipment, broken cold chain or wrong spec open a discrepancy hold
   instead.

## Layout

```
run.py                boot: init/migrate, seed, serve
schema.sql            fresh DB, all CHECKs and the one-primary-quote index
app/db.py             connection, migrations (one transaction per step)
app/auth.py           PBKDF2 210k, sessions, role gates, DB-backed throttle
app/audit.py          append-only audit writes, logged on failure
app/landed.py         the single PHP landed-cost calculation
app/alerts.py         the single source of counters + Attention Needed
app/routes/{auth,inventory,quotes,customs}.py
web/js/{app,ui,dashboard,inventory,quotes,customs}.js
tests/                36 tests
```

Views import only `web/js/ui.js`. `app.js` imports the views, so a view can be
deleted without touching the others.

## Design decisions worth knowing

- **Roles** are enforced only by FastAPI route dependencies. The SPA reads the
  role from `/api/me` and uses it to hide navigation and buttons; it is never the
  control itself.
- **Stock** is one conditional UPDATE (`... WHERE quantity_on_hand >= ?`). Lots
  are drained earliest-expiry-first in the same transaction. Manual recounts use
  `WHERE quantity_on_hand = <expected>` and return 409 if someone else moved the
  stock first.
- **GETs never write.** Alerts are derived on read, so there is nothing to
  reconcile, no write lock in a poll, and no duplicate alerts.
- **No hard deletes.** Items are `deprecated`, quotes are `rejected`, POs are
  `cancelled`. The audit log is append-only.
- **No legacy tables.** Spend is `SUM(landed_cost_php)` over received POs.

## Tests

```bash
python -m pytest -q
```

Covers role enforcement, CSRF rejection, session invalidation on password change,
20-way concurrent consumption (never negative), FEFO, optimistic recount 409,
quote→PO conversion with primary/backup, lot-captured receiving, discrepancy
holds, the watchdog, LIKE escaping, migrations and the landed-cost math.

## Deliberate limits

- One PO = one item (no `po_line` table yet).
- Storage locations are free-text strings, not a tree, so there is no cycle to
  guard.
- `POST /receive` receives the full PO quantity; partial receipt is the next step.
- The request-body cap reads `Content-Length`; a chunked body without that header
  is not measured.
