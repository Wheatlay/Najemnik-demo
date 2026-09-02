# Najemnik — focused portfolio demo

Najemnik helps a renter turn inconsistent apartment advertisements into comparable decisions. This repository is a deliberately reduced showcase extracted from a larger private application—not a second production edition of it.

The snapshot preserves the code paths that best demonstrate the project:

- deterministic monthly, annual and move-in cost calculations;
- filtering, focused comparison and ranking;
- map and commute-point visualization;
- notes and inline editing;
- evidence attached to values extracted by a local model;
- a guided product tour.

Accounts, registration, email, administration, scraping execution, imports, browser-extension distribution, quotas and production operations are outside this public snapshot.

## Demo data

The three Katowice scenarios, their contacts, URLs and nine interior images are entirely synthetic. Model-labelled text is recorded output grounded in the synthetic listing descriptions; the hosted application never calls a model.

Each browser receives a small isolated SQLite-backed guest session. **Reset demo** restores only that browser's fixtures.

## Run locally

```bash
cp .env.example .env
docker build -t najemnik-demo .
docker run --rm -p 8000:8000 --env-file .env najemnik-demo
```

Open `http://localhost:8000`. The health contract is available at `GET /healthz`.

## Where to review the code

- `core/domain/` — costs, normalization, ranking, filtering and display rules.
- `core/pipeline/demo.py` — synthetic fixture loading and reset.
- `core/pipeline/enrich/` — selected real evidence-first local-Ollama architecture, retained for code review but not called by the demo.
- `routers/pages.py` and `routers/listings_api.py` — the reduced web surface.
- `templates/` and `static/js/` — server-rendered HTMX/Alpine interface.
- `scripts/tools/verify_portfolio_demo.py` — the recruiter-flow browser verification.

See [architecture](docs/ARCHITECTURE.md), [demo safety](docs/DEMO.md), and the [Polish terminology glossary](docs/GLOSSARY.md).

Python 3.12 · FastAPI · SQLModel · SQLite · Jinja2 · HTMX · Alpine.js · Tailwind CSS · MapLibre · Ollama architecture · Pytest · Playwright · Docker

MIT licensed.
