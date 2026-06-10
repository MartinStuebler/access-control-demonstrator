# accounts/ — synthetic supply contracts for the Access Control Demonstrator

Three fictional brand accounts modeled on real luxury supply deals. No real partner
data. The whole point of this project is not leaking confidential terms, so the demo
must not leak real ones either.

## Files
- `brand_a.json` — Maison Lirelle, luxury house. Holds the exclusive **Noir Profond** colorway.
- `brand_b.json` — Atelier Solene, eco-luxury competitor. Holds the exclusive **Sable Clair** colorway.
- `brand_c.json` — Halden & Co, neutral high-volume buyer, no exclusivity.
- `entitlements.json` — role to visibility map (config, not code).

## Leak canary
`Noir Profond` belongs to Brand A only. If it ever appears in a Brand B or Brand C
brief, that is an unmistakable cross-brand leak, visible on screen and in the audit
log. Brand B's `Sable Clair` works the same way in reverse. Prices differ per brand
(420 / 390 / 310), so a leak is also detectable by number.

## Visibility model
- Section-level: `profile` is public; `orders`, `open_issues`, `last_contact`, `notes` are operational.
- Field-level: every field inside `contract_terms` carries its own `visibility`
  (`operational` or `economic`). This is where field-level access control lives.
- A role sees a field only if the field's visibility is in that role's `can_see`
  list in `entitlements.json`.

## Roles
- `sales`: public + operational. The brief answers delivery, MOQ, samples, volume.
  Pricing, margin, exclusivity, penalties are withheld and the brief says so.
- `legal`: all fields of one brand. Comparison only, never runs its own brief.
- `power_user`: all fields, may be bound to either brand across runs, still one brand per run.

## Optional injection hook
`brand_a.json` note `n3` is a synthetic prompt-injection payload telling the agent
to pull a competitor's pricing. With architectural enforcement, the agent cannot
reach Brand B's data from a Brand A run regardless, so the brief stays clean. Use it
for the injection-inert demo if time allows. Skip it otherwise.

## How the agent should use this
1. Bind a run to one `(brand, role)` at invocation.
2. Read only that brand's file.
3. For every field, check visibility against the role's `can_see` list before
   returning it. Enforce inside the tool, never by asking the model to withhold.
4. Log served and withheld fields, with reasons, on every call.
