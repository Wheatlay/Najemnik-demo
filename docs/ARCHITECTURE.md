# Showcase architecture

This repository contains one vertical product slice rather than the complete private Najemnik system.

```text
browser
  -> signed opaque guest cookie
  -> four read views: gallery / map / comparison / dashboard
  -> three mutations: edit / rank / map position
  -> user-scoped SQLite rows loaded from synthetic fixtures
```

`core/domain/` contains the original deterministic business rules. The FastAPI routers remain thin: they validate ownership, call those rules, and return Jinja/HTMX fragments. Reset deletes and reloads only the current guest's synthetic rows.

## Selected local-model code

`core/pipeline/enrich/` is retained as an inspectable sample from the private application. It shows:

- a provider boundary around local Ollama generation;
- atomic field prompts and validation;
- evidence quotations stored beside extracted values;
- deterministic fallbacks and manual-override provenance.

The selected source is not mounted as an HTTP action in this showcase. All visible model output is precomputed and grounded in `fixtures/demo_listings.json`.

## Deliberately absent

The public snapshot excludes account management, email, administration, live ingestion, browser-extension packaging, production deployment operations, migrations and private research artifacts. Their removal keeps the repository centered on the code a reviewer can actually exercise in the demo.
