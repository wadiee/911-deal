---
name: Project progress
description: Implementation status of 911 Deal Radar — what's done, what's skipped, what remains
type: project
---

## Completed pieces (as of 2026-05-01)

- **Piece 1** Foundation (models, DB, Docker, Alembic, templates) — done
- **Piece 2** AI Listing Parser (Claude Opus 4.7, normalizers, /api/listings/parse) — done
- **Piece 3** Admin UI — deliberately skipped full UI; replaced with minimal edit routes (see below)
- **Piece 4** Comp Matcher (scoring, weighting, ranking) — done
- **Piece 5** Valuation & Report Generator (deterministic, template-based) — done
- **Piece 6** Public Submit UI (/submit form, report generation, email capture) — done
- **Piece 7** BaT Scraper (full parser, batch ingestion script) — done
- **Piece 8** CnB Scraper — **skipped** (no reliable sold price extraction from CnB DOM)
- **Piece 9** Scrapers & refresh:
  - BaT refresh in `scripts/refresh.py` — done
  - CarGurus partial (`app/scrapers/cargurus.py`, `scripts/ingest_cargurus.py`) — done
  - CPO scraper — **skipped** (user decision)
  - AutoTrader/Cars.com scrapers — **skipped** (user decision)
  - ScrapeEvent logging to DB — **done (2026-05-01)**
  - Scheduled refresh integration into app startup — **deferred** (do after cloud migration)
- **Piece 10** Seed validation — not yet run
- **Piece 11** Cloud migration — documented in execution_plan.md; not yet started

## Admin UI decision

User decided not to build full admin UI. Instead:
- `GET /admin/listings` — minimal paginated table of all listings (no auth, local only)
- `GET /admin/listings/{id}` — edit form for all listing fields
- `POST /admin/listings/{id}` — save edits

No authentication on admin routes (deliberate for local dev; auth only matters when public).

## Key files

- `app/models.py` — 6 tables: Listing, PriceObservation, Report, CompMatch, EmailCapture, ScrapeEvent
- `app/scrapers/bat.py` — returns (parsed, http_status, restriction_signal) tuple
- `app/scrapers/registry.py` — unwraps tuple for public.py callers
- `scripts/ingest_bat.py` — logs ScrapeEvent per URL attempt
- `scripts/refresh.py` — logs ScrapeEvent for BaT and CarGurus metro fetches
- `alembic/versions/c3e1d2a7f501_add_scrape_events.py` — pending migration (run `alembic upgrade head`)

## Pending migration

Run `uv run alembic upgrade head` to create the scrape_events table before using the scraper scripts.

**Why:** ScrapeEvent model added 2026-05-01. Without migration, ingest/refresh scripts will fail.
**How to apply:** Always remind user to run migration when scrape_events table is needed.
