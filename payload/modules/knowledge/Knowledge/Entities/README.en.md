# Entities

Cards for the project's entities: services, libraries, applications, data stores, external systems.
What counts as an entity is up to us; one entity may span several resources. Type `entity`, lifetime —
while the entity exists.

## When to create

- The entity is asked about or touched regularly, and it is hard to get oriented quickly from the code.
- There are non-obvious relationships, invariants, historical reasons, owners.
- A resource from `Resources/resources.toml` — its card is referenced in the catalog's `entity` field.

## When not to create

- To retell the resource's code, API or README — link to them instead.
- For small units (a class, function, endpoint) — they belong in the card of a larger entity.

## Statuses

- `active` — the entity exists and is in use.
- `deprecated` — being retired but still exists; name the replacement.
- The entity is retired — delete the card and the links to it; move what matters about the replacement to its card.

## Name and creation

The file name is the entity's name: `api.md`, `billing-service.md`, `postgres-main.md`. For a resource,
it matches the resource's `name` in the catalog.

`Toolbox/tb kb new entity billing-service --title "Billing service"`

## Example (excerpt)

```markdown
title: "Billing service"
description: "Charges and invoices; the only writer to the invoices table"
resources: [billing]
## Non-obvious details
Amounts are stored in cents (int). Recalculating the previous month is forbidden after the 5th.
```
