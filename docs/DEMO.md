# Demo guide and safety contract

The public demo starts with three synthetic district-level Katowice scenarios and nine generated interiors. Reserved `.invalid` URLs and deliberately invalid `000` phone numbers prevent accidental contact.

Each browser receives a separate guest user and 24-hour session. Reset removes and reseeds only that user's demo rows. The SQLite database and copied photos are ephemeral: after a host restart, the next request recreates the schema and the next browser session recreates its fixtures.

The hosted application does not mount authentication, import, administrator, settings, ingestion or model routes. Attempts to access known production-only actions return HTTP 403 with:

```json
{"detail":"demo_mode_disabled","feature":"/requested/path"}
```

The demo performs no portal, email or Ollama calls. Recorded extraction and comparison text is identified in the interface and fixtures as precomputed output.

Render free services may spin down while idle, so the first request can be slower than later navigation. Use `/healthz` to distinguish a cold start from an application error.
