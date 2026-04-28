# 911 Deal Radar — PRD + Engineering Design

## 1. Product Requirements Document

### 1.1 Product Summary

911 Deal Radar is a Porsche 911 buying assistant that helps used-car buyers understand whether a listing is fairly priced, overpriced, risky, or attractive based on comparable cars, market context, listing details, and enthusiast-specific judgment.

The initial MVP focuses on used Porsche 911 listings in the U.S., specifically the 991.2 generation (Carrera, Carrera S, Carrera 4, Carrera 4S, GTS) and the 992.1 generation (Carrera, Carrera S, Carrera 4, Carrera 4S, GTS). GT3 is intentionally out of MVP scope and is deferred to V1.1 because of wider spec/price spread, allocation premium dynamics, and lower comp density per sub-spec. Users submit a listing URL and the product scrapes structured listing fields, then generates a buyer report with pricing range, confidence level, comparable cars, spec analysis, risk flags, and recommended questions to ask the seller.

The product does not claim to know the exact fair value of each car. Instead, it provides decision support: comparable market ranges, confidence-weighted signals, and practical buyer guidance.

### 1.2 Problem Statement

Buying a used Porsche 911 is hard because every car is meaningfully different. Price depends on generation, trim, transmission, body style, mileage, options, color, service history, accident history, ownership history, seller type, condition, modifications, and market venue.

Most public car sites show asking prices, but asking price is not the same as market-clearing price. Buyers often lack enough context to know whether a listing is actually fairly priced or merely priced similarly to other optimistic seller listings.

Existing tools such as KBB-style estimators are too generic for enthusiast cars. Auction sites have rich data, but buyers need to manually interpret comps, comments, options, and condition details.

### 1.3 Target Users

#### Primary User

A U.S.-based enthusiast buyer shopping for a used Porsche 911 in the $50k–$200k range. This user understands cars at a moderate level but wants help interpreting market comps and avoiding overpaying.

#### Secondary Users

Car photographers, car meet attendees, and local enthusiast communities who may want buying guidance, market trend summaries, or listing reviews.

#### Future Users

Dealers, brokers, PPI shops, and enthusiast marketplaces that may want lead generation, analytics, or market reports.

### 1.4 Goals

The MVP should help a user answer:

1. Is this 911 listing fairly priced compared with relevant comps?
2. What are the closest comparable cars?
3. How confident is the estimate?
4. Is this spec desirable or merely expensive?
5. What risks should the buyer investigate before moving forward?
6. What offer range or negotiation posture makes sense?

### 1.5 Non-Goals

The MVP will not:

1. Guarantee exact market value.
2. Replace a professional pre-purchase inspection.
3. Provide legal, financing, insurance, or tax advice.
4. Bypass CAPTCHAs, login walls, or other explicit anti-bot protections.
5. Cover every Porsche model or every 911 variant from day one.
6. Support real-time nationwide inventory completeness.
7. Support automated vehicle purchase transactions.

### 1.6 MVP Scope

#### Core MVP Features

##### Listing Submission

Users submit a Porsche 911 listing primarily by URL. The system attempts to scrape structured listing fields directly from the source site. The user can optionally provide:

- Asking price override
- Mileage override
- Notes

If a site cannot be scraped (e.g., explicit anti-bot block, unsupported source), the system falls back to a paste-listing-text path. The expectation in MVP is that the dominant path is URL → scrape, not manual entry.

##### Site Scrapers

The MVP ships with scrapers for the most active U.S. used-Porsche listing and auction sources, including:

- Bring a Trailer (active auctions and sold results)
- Cars and Bids (active auctions and sold results)
- Porsche Approved Certified Pre-Owned inventory
- Major dealer aggregators where terms permit (e.g., AutoTrader, Cars.com, CarGurus)
- Enthusiast classified sources where supported (e.g., Rennlist, PCA Mart) where structure allows

Each scraper produces a normalized `ParsedListing` plus a `price_observation` row. Scrapers should be written so adding a new source is a focused module change.

##### AI-Assisted Listing Parser

The system extracts structured fields from listing text:

- Year
- Generation
- Trim
- Body style
- Transmission
- Mileage
- Asking price
- Exterior color
- Interior color
- Seller type
- Location
- VIN, if available
- Options, if mentioned
- Modifications, if mentioned
- Title/accident/service-history signals, if mentioned

##### Comp Database

The system stores Porsche 911 comps populated primarily by automated scrapers, supplemented by user submissions and selective manual curation.

Each comp can represent:

- Confirmed sold auction result
- Dealer asking price
- Private-party asking price
- Removed listing with last-seen asking price
- Price drop observation
- User-submitted sale

##### Comp Matching

Given a submitted listing, the system finds the most relevant comparable cars based on:

- Generation
- Trim
- Body style
- Transmission
- Mileage band
- Model year proximity
- Seller type
- Price type
- Recency
- Condition/risk flags

##### Buyer Report

The product generates a report containing:

- Overall verdict
- Asking price
- Estimated fair-market range
- Confidence level
- Sold comp range
- Active asking comp range
- Recommended offer range
- Closest comparable cars
- Desirability analysis
- Risk flags
- Questions to ask seller
- Human-readable explanation

##### Admin Data Management

An internal admin interface allows the founder/operator to:

- Add listings manually
- Edit parsed fields
- Mark records as sold, active, removed, no-sale, or unknown
- Add expert notes
- Normalize trim/generation/transmission/body data
- Assign comp quality scores
- Review generated reports

### 1.7 Future Features

#### V1.1

- 991.2 GT3 and 992.1 GT3 coverage
- Saved searches
- Email alerts for new matching listings
- Price-drop tracking
- Report sharing link
- Basic user accounts

#### V1.2

- Stripe payment for paid reports
- $19 automated report
- $49–$99 human-assisted review
- Expand to 997.2 and 991.1 generations
- More Porsche models: Cayman, Boxster, Panamera, Taycan

#### V2

- Dealer/broker partnerships
- PPI shop lead generation
- Market trend dashboards
- Community-submitted sale results
- VIN decoding integrations
- Window sticker/options decoding
- Machine-learning assisted valuation model

### 1.8 Success Metrics

#### Product Usage

- Number of submitted listings
- Number of generated reports
- Percentage of users who view full report
- Percentage of users who submit another listing
- Number of saved listings

#### Data Quality

- Number of total comp records
- Number of confirmed sold comps
- Percentage of comps with required fields
- Percentage of reports with at least 5 close comps
- Report confidence distribution

#### Business Validation

- Email capture conversion rate
- Paid report conversion rate
- Human-review conversion rate
- Repeat usage rate
- User feedback score on report helpfulness

#### Operational Metrics

- Parser success rate
- Manual correction rate
- Report generation latency
- Background job failure rate
- LLM cost per report

### 1.9 Key Product Principles

#### Be Honest About Confidence

The system should never pretend it knows exact value. Every report should clearly state whether confidence is high, medium, or low.

#### Separate Asking Prices From Sold Prices

Seller asking price and actual transaction price are different. The product should always distinguish:

- Confirmed sold comps
- Active asking comps
- Removed listings
- Last-seen prices
- No-sale auction results

#### Explain the Why

The product should not simply output a number. It should explain why a car appears cheap, fair, expensive, desirable, or risky.

#### Scrape First, Manual As Fallback

The MVP's data backbone is automated scraping of public listing and auction sites. Manual entry exists as a fallback when a source is unsupported or blocks extraction. The analysis layer is the long-term moat, but in MVP, breadth and freshness of scraped comp data is what makes reports useful.

#### Start Narrow

The first strong wedge is not “all cars.” It is Porsche 911 buyer intelligence, starting with common enthusiast buyer trims.

---

## 2. Engineering Design Document

### 2.1 System Overview

911 Deal Radar is a Python/FastAPI web application with a Postgres database and a lightweight frontend. The system supports manual/semi-automated data ingestion, AI-assisted listing parsing, comparable-car matching, and report generation.

The first version prioritizes speed of iteration, data quality, and founder-operated workflows over full automation.

### 2.2 Recommended Tech Stack

#### Backend

- Python 3.12+
- FastAPI
- Pydantic for request/response schemas
- SQLAlchemy or SQLModel for ORM
- Alembic for migrations
- PostgreSQL as primary database

#### Frontend

For MVP:

- Jinja2 templates
- HTMX for lightweight interactivity
- Tailwind CSS

Future option:

- React or Next.js frontend if the product needs a richer UI

#### Jobs

MVP:

- APScheduler or simple cron-triggered scripts

Later:

- Celery or RQ with Redis

#### AI Integration

- OpenAI or Anthropic API for listing parsing and report generation
- Structured JSON output for parser stage
- Prompt templates stored in code or database

#### Hosting

MVP-friendly options:

- Render
- Railway
- Fly.io
- Supabase or Neon for managed Postgres

#### Storage

- Postgres for structured listing data
- Object storage later for screenshots/images if needed

### 2.3 High-Level Architecture

```text
User Browser
    |
    v
FastAPI Web App
    |-- Jinja2/HTMX frontend
    |-- API routes
    |-- Auth/session layer, later
    |-- Listing parser service
    |-- Comp matching service
    |-- Report generation service
    |-- Admin data management
    |
    v
Postgres Database
    |-- listings
    |-- price_observations
    |-- reports
    |-- comp_matches
    |-- users, later
    |-- saved_searches, later
    |
    v
Background Jobs
    |-- price tracking, later
    |-- listing status refresh, later
    |-- data quality checks

External Services
    |-- LLM provider
    |-- optional VIN/options decoder, later
    |-- optional payment provider, later
```

### 2.4 Major User Flows

#### Flow 1: User Submits a Listing

1. User opens `/submit`.
2. User pastes listing URL and/or listing text.
3. Backend stores raw submission.
4. Parser service extracts structured listing fields.
5. User can review extracted fields.
6. User submits confirmed fields.
7. System creates or updates a `listing` record.
8. System runs comp matching.
9. System generates buyer report.
10. User sees report page.

#### Flow 2: Admin Adds a Comp Manually

1. Admin opens `/admin/listings/new`.
2. Admin enters listing/sale details.
3. System normalizes generation, trim, transmission, body style, price type, and source.
4. Admin saves record.
5. Record becomes available for future comp matching.

#### Flow 3: Generate Buyer Report

1. Load target listing.
2. Validate minimum required fields.
3. Find candidate comps.
4. Score comp similarity.
5. Weight comps by data quality and price type.
6. Calculate sold comp range, active asking range, and estimated market range.
7. Generate explanation with LLM using structured comp summary.
8. Persist report.
9. Render report page.

### 2.5 Data Model

#### users

For MVP, users can be optional. Initial reports can be anonymous. Add user accounts when saved searches or paid reports are introduced.

```sql
users (
    id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

#### listings

Represents a vehicle listing, auction result, or manually entered comp.

```sql
listings (
    id UUID PRIMARY KEY,
    source TEXT NOT NULL,
    source_url TEXT,
    status TEXT NOT NULL,
    price_type TEXT NOT NULL,

    asking_price NUMERIC(12, 2),
    sold_price NUMERIC(12, 2),
    last_seen_price NUMERIC(12, 2),

    date_seen DATE,
    date_sold DATE,
    last_seen_at TIMESTAMPTZ,

    year INTEGER,
    make TEXT NOT NULL DEFAULT 'Porsche',
    model TEXT NOT NULL DEFAULT '911',
    generation TEXT,
    trim TEXT,
    body_style TEXT,
    transmission TEXT,
    drivetrain TEXT,

    mileage INTEGER,
    exterior_color TEXT,
    interior_color TEXT,
    location TEXT,
    seller_type TEXT,
    vin TEXT,

    title_status TEXT,
    accident_reported BOOLEAN,
    owner_count INTEGER,
    cpo BOOLEAN,

    options JSONB,
    modifications JSONB,
    raw_text TEXT,
    normalized_notes TEXT,
    expert_notes TEXT,

    comp_quality TEXT,
    confidence_score NUMERIC(5, 2),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

Recommended status values:

```text
ACTIVE
SOLD
NO_SALE
REMOVED_UNKNOWN
WITHDRAWN
EXPIRED
UNKNOWN
```

Recommended price types:

```text
ASKING_PRICE
SOLD_PRICE
BID_TO_PRICE
PRICE_DROP
LAST_SEEN_PRICE
UNKNOWN_FINAL
```

#### price_observations

Tracks price changes over time for the same listing.

```sql
price_observations (
    id UUID PRIMARY KEY,
    listing_id UUID NOT NULL REFERENCES listings(id),
    observed_at TIMESTAMPTZ NOT NULL,
    observed_price NUMERIC(12, 2),
    observation_type TEXT NOT NULL,
    source_url TEXT,
    raw_snapshot TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

Observation types:

```text
INITIAL_ASK
PRICE_DROP
PRICE_INCREASE
LAST_SEEN
REMOVED
SOLD_CONFIRMED
NO_SALE
```

#### reports

Stores generated buyer reports.

```sql
reports (
    id UUID PRIMARY KEY,
    target_listing_id UUID NOT NULL REFERENCES listings(id),
    report_version TEXT NOT NULL,

    verdict TEXT,
    confidence_level TEXT,
    asking_price NUMERIC(12, 2),
    estimated_low NUMERIC(12, 2),
    estimated_high NUMERIC(12, 2),
    recommended_offer_low NUMERIC(12, 2),
    recommended_offer_high NUMERIC(12, 2),

    sold_comp_summary JSONB,
    active_comp_summary JSONB,
    risk_flags JSONB,
    desirability_factors JSONB,
    seller_questions JSONB,

    report_markdown TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

#### comp_matches

Stores which comps were used for a report.

```sql
comp_matches (
    id UUID PRIMARY KEY,
    report_id UUID NOT NULL REFERENCES reports(id),
    comp_listing_id UUID NOT NULL REFERENCES listings(id),
    similarity_score NUMERIC(5, 2) NOT NULL,
    data_weight NUMERIC(5, 2) NOT NULL,
    final_weight NUMERIC(5, 2) NOT NULL,
    match_reason JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

### 2.6 Core Backend Modules

#### scraper_registry

The primary ingestion path. Each supported source has a dedicated scraper module that, given a URL, returns a `ParsedListing` plus a raw snapshot for re-parsing.

Responsibilities:

- URL routing: choose the right scraper for a given source.
- Page fetch with reasonable rate limiting and a stable user-agent.
- Source-specific HTML/JSON extraction into `ParsedListing`.
- Capture sold/active/no-sale state for auction sources.
- Persist raw snapshot alongside parsed fields.

If no scraper matches the URL, the request falls through to `listing_parser` (paste-text path).

#### listing_parser

The fallback path for URLs we cannot scrape and for users pasting raw listing text.

Inputs:

- URL, optional
- Raw listing text
- Optional manually entered price/mileage

Outputs:

- Parsed listing object
- Missing fields
- Parser confidence
- Warnings

Implementation approach:

1. Pre-clean text.
2. Send structured extraction prompt to LLM.
3. Validate output with Pydantic schema.
4. Normalize enums.
5. Store raw and parsed data.

Important rule: Both scraper output and parser output should be reviewable by admin. Neither is trusted blindly.

#### normalizer

Responsible for canonicalizing values.

Examples:

- “Carrera 4S” → `CARRERA_4S`
- “PDK automatic” → `PDK`
- “manual 6-speed” → `MANUAL`
- “coupe” → `COUPE`
- “991.1” inferred from year and trim when possible

#### comp_matcher

Responsible for finding and ranking comparable cars.

Inputs:

- Target listing
- Candidate comp pool

Outputs:

- Ranked comp list
- Similarity score
- Data quality weight
- Match explanation

Candidate filters:

1. Make/model must be Porsche 911.
2. Prefer same generation.
3. Prefer same or adjacent trim.
4. Prefer same body style.
5. Prefer same transmission.
6. Mileage should be within reasonable band.
7. Prefer recent comps.
8. Prefer confirmed sold prices when estimating market-clearing value.

#### valuation_service

Responsible for turning comps into price ranges.

Outputs:

- Sold comp range
- Active asking range
- Estimated market range
- Recommended offer range
- Confidence level

Early implementation can use heuristic weighted percentiles rather than ML.

Example weighting:

```text
Confirmed sold auction result: 1.00
Dealer confirmed sale: 0.80
User-submitted sale with evidence: 0.70
Removed listing / last-seen price: 0.40
Active asking price: 0.25
Stale listing: 0.10
```

#### report_generator

Responsible for generating user-facing explanation.

Inputs:

- Target listing
- Comp summary
- Valuation result
- Risk flags
- Desirability factors

Outputs:

- Markdown report
- Structured report fields

The LLM should receive structured facts only. It should not invent comps, prices, or risks not present in the data.

### 2.7 Comp Matching Heuristic

Initial similarity score can be rule-based.

Example scoring:

```text
same generation: +25
same trim: +25
same transmission: +15
same body style: +10
mileage within 10k: +10
model year within 2 years: +5
same seller type: +3
similar title/accident status: +5
recent comp within 12 months: +7
```

Penalty examples:

```text
different generation: -30
different trim class: -20
different transmission: -15
accident/branded title mismatch: -15
modified vs stock mismatch: -10
mileage difference > 40k: -20
stale comp older than 3 years: -10
```

This can later evolve into a trained ranking model, but a transparent heuristic is better for MVP.

### 2.8 Valuation Strategy

The system should avoid single-point price predictions. It should produce ranges with confidence.

#### Sold Comp Range

Use confirmed sold comps only, weighted by similarity and recency.

#### Active Asking Range

Use active listings and dealer/private asking prices. Clearly label as seller expectation, not transaction price.

#### Estimated Market Range

Use sold comps as primary signal. Use active asking prices as secondary signal only when sold comps are sparse.

#### Offer Range

Recommended offer should usually be below asking price and derived from:

- Estimated market range
- Seller type
- Days on market
- Price drop history
- Desirability
- Confidence level

### 2.9 Confidence Model

Report confidence should be based on data quality, comp similarity, and sample size.

#### High Confidence

- At least 5 close confirmed sold comps
- Same generation, trim, body, and transmission
- Similar mileage band
- Recent data

#### Medium Confidence

- Some close sold comps
- Some fields require adjustment
- Active listings supplement sold comps

#### Low Confidence

- Rare spec
- Sparse sold comps
- Heavy modifications
- Unusual title/accident history
- GT/limited model
- Missing key fields

Example output:

```text
Confidence: Medium
Reason: There are several close 991.2 Carrera S PDK coupe comps, but this listing has lower mileage and unusually strong options, so the range is wider.
```

### 2.10 API Design

#### Public Web Routes

```text
GET  /
GET  /submit
POST /submit
GET  /reports/{report_id}
```

#### Admin Routes

```text
GET  /admin/listings
GET  /admin/listings/new
POST /admin/listings
GET  /admin/listings/{listing_id}
POST /admin/listings/{listing_id}
GET  /admin/reports
```

#### JSON API Routes

```text
POST /api/listings/parse
POST /api/listings
GET  /api/listings/{listing_id}
POST /api/reports/generate
GET  /api/reports/{report_id}
GET  /api/comps?listing_id={listing_id}
```

### 2.11 Example Pydantic Models

```python
from pydantic import BaseModel, Field
from typing import Optional, list
from decimal import Decimal

class ParsedListing(BaseModel):
    year: Optional[int] = None
    make: str = "Porsche"
    model: str = "911"
    generation: Optional[str] = None
    trim: Optional[str] = None
    body_style: Optional[str] = None
    transmission: Optional[str] = None
    mileage: Optional[int] = None
    asking_price: Optional[Decimal] = None
    exterior_color: Optional[str] = None
    interior_color: Optional[str] = None
    location: Optional[str] = None
    seller_type: Optional[str] = None
    vin: Optional[str] = None
    options: list[str] = Field(default_factory=list)
    modifications: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)
    parser_confidence: float = 0.0
```

### 2.12 Admin Workflow

The admin workflow is critical because early data quality determines product quality.

Admin should be able to:

1. Paste listing text.
2. Run parser.
3. Review extracted fields.
4. Correct trim/body/transmission/generation.
5. Add expert notes.
6. Set comp quality.
7. Save to comp database.

This is more important than building a polished public UI first.

### 2.13 Data Acquisition Strategy

#### Phase 1: Scraper-Driven Seed Dataset

Target: 2,000+ initial rows for 991.2 and 992.1 in scope.

The seed dataset is built primarily by running the MVP's scrapers against public listing and auction sources, then filtering down to in-scope generations and trims. Rough target mix:

- ~800 confirmed sold comps from auction sources (BaT, Cars and Bids)
- ~800 active dealer/private asking listings (CPO inventory, AutoTrader, Cars.com, CarGurus)
- ~300 historical/removed listings recovered from auction archives
- ~100 manually annotated expert examples for cases where scrapers miss key signals (heavy options, unusual condition)

#### Phase 2: Continuous Scraping

Scrapers run on a schedule to refresh active listings, capture price drops, and detect sold/no-sale outcomes. Each run produces `price_observation` rows so listing history is preserved.

#### Phase 3: User-Submitted Listings

Users submit URLs that get parsed by the same scraper pipeline; pasted text is the fallback. User submissions feed back into the comp database after review.

#### Phase 4: Partnerships or Licensed Data

If traction exists and scraping coverage hits limits, explore data partnerships, dealer feeds, or licensed market data.

### 2.14 Scraping and Compliance Principles

The MVP leans into scraping public listing and auction pages to build comp coverage quickly. Compliance guardrails exist to keep the operation legally defensible, not to discourage scraping.

Rules:

1. Scrape public, non-authenticated listing pages aggressively but politely (reasonable rate limits, identifying user agent, no thundering-herd retries).
2. Do not bypass CAPTCHAs, login walls, or other explicit anti-bot protections.
3. Do not scrape pages that require an account to access.
4. Honor robots.txt where it materially restricts the listing pages we want; for sources where it does not, scrape with reasonable courtesy.
5. Cache scraped pages so the same URL is not refetched unnecessarily.
6. Persist the raw HTML/JSON snapshot alongside the parsed record so re-parsing does not require re-scraping.
7. Treat manual/user-submitted text as a fallback path for sources we cannot or should not scrape.
8. The product's defensible value is the analysis, normalization, and comp-matching layer on top of the data — not the scraped data itself. Keep that in mind when prioritizing.

#### Scraper Restriction Logging

The MVP keeps every supported source enabled by default (including stricter-ToS sources like AutoTrader, Cars.com, and CarGurus) and decides what to back off from based on observed behavior, not assumption. To support that decision, every scraper run records a structured event when it is restricted.

For each blocked or degraded fetch, log:

- Source and URL pattern
- Timestamp and run ID
- HTTP status code (e.g., 403, 429, 503)
- Restriction signal: rate limit, CAPTCHA challenge page, JS-only render, IP block, ToS-style block page, robots.txt disallow, structural change (selectors no longer match)
- Headers/response excerpt that identified the signal
- Whether retry-after / cooldown was honored
- Cumulative block rate for that source over the last N runs

These logs feed a small operator dashboard (or admin page) that surfaces per-source health: success rate, restriction-type breakdown, and trend over time. The decision to deprioritize, throttle further, or remove a source is made from this data — not pre-emptively.

### 2.15 Security and Privacy

MVP considerations:

- Do not store sensitive user data unless needed.
- Do not expose admin pages publicly without authentication.
- Sanitize raw listing text before rendering.
- Rate-limit expensive report generation endpoints.
- Store LLM API keys in environment variables.
- Log LLM costs and failures.

### 2.16 Observability

Track:

- Parser success/failure rate
- Report generation failures
- LLM latency and cost
- Number of comps found per report
- Confidence distribution
- Admin correction rate
- Background job failures
- Per-scraper success rate, restriction-type breakdown, and trend (see 2.14 Scraper Restriction Logging)

### 2.17 Deployment Plan

#### MVP Deployment

- FastAPI app deployed to Render/Railway/Fly.io
- Managed Postgres via Supabase/Neon/Render
- Environment variables for DB and LLM API keys
- Static files served by FastAPI or CDN later

#### Local Development

Use Docker Compose:

- app
- postgres
- optional redis later

Example local commands:

```text
uv init
uv add fastapi uvicorn sqlalchemy alembic pydantic psycopg[binary] jinja2 python-multipart
uv run uvicorn app.main:app --reload
```

### 2.18 MVP Milestones

#### Milestone 1: Skeleton App

- FastAPI app running locally
- Postgres connected
- Listings table created
- Basic landing page
- Basic submit form

#### Milestone 2: First Two Scrapers

- Build scrapers for Bring a Trailer and Cars and Bids (sold + active)
- Filter to 991.2 and 992.1 in-scope trims
- Store raw snapshot + parsed `ParsedListing`
- Admin can review and correct parsed fields

#### Milestone 3: AI Parser Fallback

- Paste-listing-text fallback path for unsupported sources
- Reuse the same `ParsedListing` schema
- LLM extraction validated with Pydantic
- Used when scraper for a URL is unavailable

#### Milestone 4: Additional Scrapers

- Porsche CPO inventory
- Dealer aggregators (AutoTrader, Cars.com, CarGurus) where terms permit
- Scheduled refresh job emitting `price_observation` rows

#### Milestone 5: Comp Matching

- Given target listing, find similar comps
- Display ranked comps
- Show why each comp matched

#### Milestone 6: Report Generation

- Generate valuation range
- Generate markdown explanation
- Store report
- Render report page

#### Milestone 7: Seed Dataset Validation

- Confirm scraped dataset reaches the Phase 1 target volume
- Generate reports against in-scope listings
- Refine matching heuristic and weighting

#### Milestone 8: Public MVP

- Launch simple landing page
- Allow email capture
- Allow listing-URL submissions
- Founder reviews first reports if needed

### 2.19 Key Risks and Mitigations

#### Risk: Sparse or noisy comp data

Mitigation:

Start narrow. Focus on common 911 segments before rare models. Use confidence labels and widen price ranges.

#### Risk: Listing price is not sale price

Mitigation:

Always separate sold comps from active asking comps. Weight active listings lower.

#### Risk: Scraping is blocked

Mitigation:

Use manual/user-submitted listing text. Treat scraping as optional, not core.

#### Risk: LLM hallucination

Mitigation:

Provide structured facts to LLM. Validate parser outputs. Persist exact comps used. Do not allow LLM to invent prices or sources.

#### Risk: Too broad too early

Mitigation:

Limit MVP to Porsche 911 and selected generations/trims.

#### Risk: Frontend consumes too much time

Mitigation:

Use Jinja2 + HTMX + Tailwind for MVP. Avoid React until needed.

### 2.20 Open Questions

1. Should the first reports be free for email capture or paid from day one?
2. Should the initial user experience require manual review before showing a report?
3. Which scraper sources should be prioritized first for breadth: BaT + Cars and Bids (sold) and Porsche CPO + AutoTrader (active), with dealer aggregators second?
4. Should the product support photo upload or screenshots in MVP?
5. Should the comp database be private, public, or partially visible?
6. How should the scraper handle 992.1 GT3 listings that show up on in-scope sources — silently ignore, or store but not yet expose in reports?

---

## 3. Suggested MVP Positioning

### Landing Page Headline

The Porsche 911 buying assistant for enthusiasts who do not want to overpay.

### Subheadline

Paste a 911 listing and get a market-aware buyer report with comparable cars, fair price range, risk flags, and negotiation guidance.

### Early CTA

Get a free 911 listing sanity check.

### Paid CTA Later

Get a detailed human-assisted 911 listing review for $49.

---

## 4. Example Report Shape

```text
Verdict: Fair but slightly expensive

Asking Price: $91,000
Estimated Market Range: $80,000–$87,000
Recommended Offer Range: $83,000–$86,000
Confidence: Medium

Summary:
This appears to be a clean 991.2 Carrera S coupe with PDK and moderate mileage. Compared with recent sold comps, the asking price is above the likely clearing range. Compared with active dealer listings, it is not unusually high, but active asking prices are weaker signals than confirmed sales.

Why it may be desirable:
- Carrera S coupe is a strong mainstream 911 configuration
- Mileage is reasonable
- Options may improve desirability if Sport Chrono/Sport Exhaust are present

Risk flags:
- Need service history
- Need accident/paintwork verification
- Need tire/brake condition
- Need over-rev/DME report if manual, less relevant for PDK but still useful in a PPI context

Questions to ask seller:
- Can you provide full service records?
- Has the car had paintwork or accident repair?
- Are tires and brakes recent?
- Is the original window sticker available?
- Would you allow a PPI?

Deal advice:
Unless the car has exceptional options, CPO coverage, and very clean history, I would not treat the asking price as true market value. A reasonable opening offer may be in the low-to-mid $80k range.
```

---

## 5. Recommended First Implementation Order

The order below is optimized for testability: each piece can be verified before the next one starts. Scrapers are a scaling mechanism, not a prerequisite. The fastest path to a real product test is parser → manual seed comps → comp matcher → report generator.

### Piece 1 — Foundation
- Create FastAPI skeleton with Docker Compose (app + postgres).
- Create database schema for listings, price_observations, reports, and comp_matches using Alembic.
- Add a health check route and a `/` placeholder page.

**Test gate:** `uv run uvicorn app.main:app --reload` serves a page and the DB connection succeeds.

### Piece 2 — AI Listing Parser
- Build `POST /api/listings/parse`: accepts raw listing text, calls LLM, validates output with Pydantic `ParsedListing`.
- Build the `normalizer` module: canonicalize generation, trim, transmission, body style.
- Return missing fields list and parser confidence score alongside the parsed result.

**Test gate:** Paste 10 real 911 listings from BaT and CnB. Verify generation, trim, transmission, and mileage extract correctly across the variety.

### Piece 3 — Admin Comp Entry and Manual Seed
- Build `/admin/listings/new` form (Jinja2): runs the AI parser to pre-fill fields, then lets the operator correct them before saving.
- Build `/admin/listings` list view.
- Manually enter 30–50 real comps from BaT and CnB sold results to create the seed dataset.

**Test gate:** Add a comp, correct its fields, set comp quality, and confirm the record appears correctly in the DB.

### Piece 4 — Comp Matcher
- Build `comp_matcher` module using the rule-based scoring heuristic defined in section 2.7.
- Build `GET /api/comps?listing_id={id}`: returns ranked comps with similarity scores and match reasons.

**Test gate:** Submit a known 991.2 Carrera S PDK listing. Verify top comps are relevant and that mismatched trims or generations score lower.

### Piece 5 — Valuation and Report Generator
- Build `valuation_service`: weighted percentile ranges from comps using the weights in section 2.8.
- Build `report_generator`: LLM receives structured facts only and returns verdict plus markdown. LLM must not invent prices or comps not in the data.
- Build `POST /api/reports/generate` and `GET /reports/{report_id}` render page.

**Test gate:** Generate a report on a listing you know well. Show it to a Porsche buyer. Ask: “Did this help you understand the listing better than the listing site did?” This is the first real product test.

### Piece 6 — Public Submit UI
- Build `/submit` page: accepts URL or pasted text.
- Display extracted fields for user review and correction before generating the report.
- Link to the report page on completion.
- Add an email capture field (capture only for now).

**Test gate:** Share the URL with 3–5 car friends and observe them using it without assistance.

### Piece 7 — BaT Scraper
- Build `scraper_registry` router: maps a URL to the correct scraper module.
- Build the BaT scraper: sold results and active auctions → `ParsedListing` + raw HTML snapshot stored.
- Filter to 991.2 and 992.1 in-scope trims only.

**Test gate:** Run against 50 BaT sold results. Compare auto-parsed fields to manually entered equivalents and measure the correction rate.

### Piece 8 — Cars and Bids Scraper
- Build the CnB scraper using the same module shape as BaT.
- Sold results and active auctions → `ParsedListing` + raw snapshot.

**Test gate:** Same correction-rate check as Piece 7.

### Piece 9 — CPO and Dealer Aggregator Scrapers
- Build scrapers for Porsche CPO inventory, AutoTrader, Cars.com, and CarGurus where terms permit.
- Add a scheduled refresh job that emits `price_observation` rows on each run.
- Implement scraper restriction logging as defined in section 2.14.

**Test gate:** Scheduled job runs, price_observation rows are created, and the per-source health log shows success and restriction rates.

### Piece 10 — Seed Validation and Tuning
- Confirm the comp dataset reaches the Phase 1 target (2,000+ rows, roughly per the mix in section 2.13).
- Generate reports across many listings and review quality.
- Tune similarity weights and valuation heuristics based on observed output.
- Use the admin correction rate to identify remaining parser weaknesses.

**Test gate:** Reports with at least 5 close comps for the most common 991.2 and 992.1 specs. Confidence distribution is not dominated by Low.

---

The first real product test is not whether the scraper works. It is whether a Porsche buyer says: “This report helped me understand the listing better than the listing site did.”

