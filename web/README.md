# Web face — a presentation layer over the governed backend

A single local page that makes the access-control demo **visual**. It is a face, not a
brain: it adds **zero enforcement**. Every access decision is made by the existing,
tested backend (`src/policy.py`, `src/tools.py` — the same path the CLI's
`--backend local` and the 36 Python tests use). This layer only calls the governed tools
and renders what they return. Delete this folder and every security guarantee is
untouched.

## Run it (offline, no API key, instant)

```bash
cd ~/Documents/my_projects/access-control-layer
source .venv/bin/activate
pip install -r web/requirements.txt      # one-time: installs Flask
python -m web.app                         # serves http://127.0.0.1:5055
```

Open <http://127.0.0.1:5055>. No Firebase, no emulator, no Anthropic API call — the
deterministic governed path (`GovernedTools` / `compose_briefing`) runs in-process.

## The demo

1. Pick **Brand A / sales**, click **Generate briefing** — operational fields show; the
   economic fields (`unit price`, `exclusivity`, …) are listed by **name only**, struck
   through and tagged *“withheld at your access level.”*
2. Change the role to **legal** (or **power_user**), click again — same query, and now the
   economic **values** appear. That visual swap is the demo.
3. Click **Attempt to pull the rival brand's data** — the cross-brand request goes through
   the real policy engine, the refusal is shown, and a line confirms the rival brand was
   never accessed.

## Why the page cannot leak a withheld value

The browser is sent **only served (entitled) values plus the NAMES of withheld fields** —
never a withheld value. This is structural, not a CSS trick:

- `GovernedTools._gather_contract_terms()` puts only `{field, code, reason}` into its
  withheld manifest — a withheld **value is never in the record**.
- `web/app.py` builds the response from `served` (entitled) + `withheld[].field` (names).
  It **never** calls `store.get_account()`, so a withheld value is never even loaded into
  the web layer. It cannot send what it never holds.

Expand *“Show the exact JSON the server sent this browser”* under any brief to see the raw
payload: for `sales`, the economic field names appear under `contract_terms.withheld`, and
their values appear **nowhere** in the response.

## Endpoints

| Route | Purpose |
|---|---|
| `GET /` | the page |
| `POST /api/brief` `{brand, role, query}` | governed brief: `contract_terms.served` (values) + `contract_terms.withheld` (names) |
| `POST /api/cross-brand` `{brand, role}` | fires `decide()` against a rival brand; returns the refusal + `rival_accessed: false` |
