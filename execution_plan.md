# 911 Deal Radar — Execution Plan for AI Agents

This document provides piece-by-piece implementation instructions for building the 911 Deal Radar MVP. Each piece has a clear scope, file list, and a test gate that must pass before moving to the next piece. Instructions are written for AI coding agents executing autonomously.

---

## Global Conventions

- Language: Python 3.12+
- Package manager: `uv` (not pip, not poetry)
- Web framework: FastAPI
- ORM: SQLModel (combines SQLAlchemy + Pydantic)
- Migrations: Alembic
- Templates: Jinja2
- CSS: Tailwind CSS via CDN in templates (no build step for MVP)
- Frontend interactivity: HTMX via CDN
- LLM: Anthropic Claude API (use `anthropic` Python SDK)
- Database: PostgreSQL
- Local dev: Docker Compose
- All IDs: UUID v4
- All timestamps: TIMESTAMPTZ stored in UTC
- Money: `NUMERIC(12, 2)` in DB, `Decimal` in Python
- Environment variables: loaded via `python-dotenv` from `.env` file (never hardcoded)
- Do not write docstrings or inline comments unless the behavior would surprise a reader
- Do not add features beyond what is explicitly described in each piece

---

## Repository Structure Target

```
911-deal/
├── app/
│   ├── main.py                  # FastAPI app factory, router registration
│   ├── database.py              # DB engine, session dependency
│   ├── models.py                # SQLModel table models
│   ├── schemas.py               # Pydantic request/response schemas (non-table)
│   ├── config.py                # Settings loaded from env vars
│   ├── normalizer.py            # Canonicalize trim/generation/transmission/body
│   ├── listing_parser.py        # LLM-based text → ParsedListing
│   ├── comp_matcher.py          # Comp scoring and ranking
│   ├── valuation_service.py     # Price range calculations
│   ├── report_generator.py      # LLM report generation
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── registry.py          # URL → scraper routing
│   │   ├── bat.py               # Bring a Trailer scraper
│   │   ├── cnb.py               # Cars and Bids scraper
│   │   ├── cpo.py               # Porsche CPO scraper
│   │   └── aggregators.py       # AutoTrader / Cars.com / CarGurus scrapers
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── public.py            # /, /submit, /reports/{id}
│   │   ├── admin.py             # /admin/* routes
│   │   └── api.py               # /api/* JSON routes
│   └── templates/
│       ├── base.html
│       ├── index.html
│       ├── submit.html
│       ├── report.html
│       ├── admin/
│       │   ├── listings.html
│       │   ├── listing_new.html
│       │   └── listing_detail.html
│       └── partials/
│           └── comp_card.html
├── alembic/
│   ├── env.py
│   └── versions/
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── pyproject.toml
└── main.py                      # Entry point: `uv run python main.py`
```

---

## Piece 1 — Foundation

**Goal:** App runs locally, DB connects, nothing crashes.

### 1.1 Initialize the project

Run the following commands in order:

```bash
uv init
uv add fastapi uvicorn sqlmodel alembic psycopg[binary] pydantic pydantic-settings jinja2 python-multipart python-dotenv anthropic httpx
```

### 1.2 Create `docker-compose.yml`

```yaml
version: "3.9"
services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - postgres
    volumes:
      - .:/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: dealradar
      POSTGRES_PASSWORD: dealradar
      POSTGRES_DB: dealradar
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

### 1.3 Create `Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install uv && uv sync
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 1.4 Create `.env.example`

```
DATABASE_URL=postgresql+psycopg://dealradar:dealradar@localhost:5432/dealradar
ANTHROPIC_API_KEY=your_key_here
ADMIN_SECRET=change_me
```

Copy `.env.example` to `.env` and fill in real values. Never commit `.env`.

### 1.5 Create `app/config.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    anthropic_api_key: str
    admin_secret: str = "change_me"

    class Config:
        env_file = ".env"

settings = Settings()
```

### 1.6 Create `app/database.py`

```python
from sqlmodel import SQLModel, create_engine, Session
from app.config import settings

engine = create_engine(settings.database_url)

def get_session():
    with Session(engine) as session:
        yield session

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
```

### 1.7 Create `app/models.py`

Define all four tables as SQLModel classes. Use `Field(default_factory=uuid4)` for UUID primary keys. All `created_at` and `updated_at` fields use `default_factory=datetime.utcnow`. Include all columns from the data model in section 2.5 of the PRD.

```python
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB

class Listing(SQLModel, table=True):
    __tablename__ = "listings"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source: str
    source_url: Optional[str] = None
    status: str  # ACTIVE, SOLD, NO_SALE, REMOVED_UNKNOWN, WITHDRAWN, EXPIRED, UNKNOWN
    price_type: str  # ASKING_PRICE, SOLD_PRICE, BID_TO_PRICE, PRICE_DROP, LAST_SEEN_PRICE, UNKNOWN_FINAL

    asking_price: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    sold_price: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    last_seen_price: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)

    date_seen: Optional[datetime] = None
    date_sold: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    year: Optional[int] = None
    make: str = "Porsche"
    model: str = "911"
    generation: Optional[str] = None   # e.g. "991.2", "992.1"
    trim: Optional[str] = None          # e.g. "CARRERA_S", "CARRERA_4S", "GTS"
    body_style: Optional[str] = None    # COUPE, CABRIOLET, TARGA
    transmission: Optional[str] = None  # PDK, MANUAL
    drivetrain: Optional[str] = None    # RWD, AWD

    mileage: Optional[int] = None
    exterior_color: Optional[str] = None
    interior_color: Optional[str] = None
    location: Optional[str] = None
    seller_type: Optional[str] = None   # DEALER, PRIVATE, AUCTION, CPO
    vin: Optional[str] = None

    title_status: Optional[str] = None
    accident_reported: Optional[bool] = None
    owner_count: Optional[int] = None
    cpo: Optional[bool] = None

    options: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    modifications: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    raw_text: Optional[str] = None
    normalized_notes: Optional[str] = None
    expert_notes: Optional[str] = None

    comp_quality: Optional[str] = None   # HIGH, MEDIUM, LOW
    confidence_score: Optional[Decimal] = Field(default=None, max_digits=5, decimal_places=2)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PriceObservation(SQLModel, table=True):
    __tablename__ = "price_observations"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    listing_id: uuid.UUID = Field(foreign_key="listings.id")
    observed_at: datetime
    observed_price: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    observation_type: str  # INITIAL_ASK, PRICE_DROP, PRICE_INCREASE, LAST_SEEN, REMOVED, SOLD_CONFIRMED, NO_SALE
    source_url: Optional[str] = None
    raw_snapshot: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Report(SQLModel, table=True):
    __tablename__ = "reports"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    target_listing_id: uuid.UUID = Field(foreign_key="listings.id")
    report_version: str = "1.0"

    verdict: Optional[str] = None
    confidence_level: Optional[str] = None  # HIGH, MEDIUM, LOW
    asking_price: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    estimated_low: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    estimated_high: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    recommended_offer_low: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    recommended_offer_high: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)

    sold_comp_summary: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    active_comp_summary: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    risk_flags: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    desirability_factors: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    seller_questions: Optional[dict] = Field(default=None, sa_column=Column(JSONB))

    report_markdown: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CompMatch(SQLModel, table=True):
    __tablename__ = "comp_matches"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    report_id: uuid.UUID = Field(foreign_key="reports.id")
    comp_listing_id: uuid.UUID = Field(foreign_key="listings.id")
    similarity_score: Decimal = Field(max_digits=5, decimal_places=2)
    data_weight: Decimal = Field(max_digits=5, decimal_places=2)
    final_weight: Decimal = Field(max_digits=5, decimal_places=2)
    match_reason: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### 1.8 Set up Alembic

```bash
alembic init alembic
```

In `alembic/env.py`, import `SQLModel` metadata and set `target_metadata = SQLModel.metadata`. Set the `sqlalchemy.url` to read from the `DATABASE_URL` environment variable.

Generate and apply the first migration:

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

### 1.9 Create `app/main.py`

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.routers import public, admin, api

app = FastAPI(title="911 Deal Radar")

app.include_router(public.router)
app.include_router(admin.router, prefix="/admin")
app.include_router(api.router, prefix="/api")

@app.get("/health")
def health():
    return {"status": "ok"}
```

### 1.10 Create stub routers

Create `app/routers/public.py`, `app/routers/admin.py`, and `app/routers/api.py`. Each file should define an `APIRouter` and include at least one stub route that returns `{"status": "stub"}` so the app starts without errors.

### 1.11 Create `app/templates/base.html`

Minimal HTML5 base template. Include Tailwind CSS via CDN and HTMX via CDN in the `<head>`. Define a `{% block content %}{% endblock %}` body area.

### 1.12 Create `app/templates/index.html`

Extends `base.html`. Shows the app name and a placeholder message: "911 Deal Radar — coming soon."

### Test gate

Start the app: `docker-compose up` or `uv run uvicorn app.main:app --reload`

Verify:
- `GET /` returns the index page with no errors
- `GET /health` returns `{"status": "ok"}`
- Alembic migrations applied with all four tables present in the DB

---

## Piece 2 — AI Listing Parser

**Goal:** `POST /api/listings/parse` accepts raw listing text and returns a structured `ParsedListing`.

### 2.1 Create `app/schemas.py`

Define `ParsedListing` as a Pydantic `BaseModel` (not a table). This is the shared schema used by the parser, scrapers, and admin form pre-fill.

```python
from pydantic import BaseModel, Field
from typing import Optional
from decimal import Decimal

class ParsedListing(BaseModel):
    year: Optional[int] = None
    make: str = "Porsche"
    model: str = "911"
    generation: Optional[str] = None
    trim: Optional[str] = None
    body_style: Optional[str] = None
    transmission: Optional[str] = None
    drivetrain: Optional[str] = None
    mileage: Optional[int] = None
    asking_price: Optional[Decimal] = None
    sold_price: Optional[Decimal] = None
    exterior_color: Optional[str] = None
    interior_color: Optional[str] = None
    location: Optional[str] = None
    seller_type: Optional[str] = None
    vin: Optional[str] = None
    options: list[str] = Field(default_factory=list)
    modifications: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)
    title_status: Optional[str] = None
    accident_reported: Optional[bool] = None
    owner_count: Optional[int] = None
    cpo: Optional[bool] = None
    parser_confidence: float = 0.0
    missing_fields: list[str] = Field(default_factory=list)
```

### 2.2 Create `app/normalizer.py`

The normalizer takes raw string values and returns canonical enum strings. All comparisons should be case-insensitive. Return `None` if input does not match any known pattern — do not guess.

Required normalization functions:

- `normalize_generation(raw: str) -> Optional[str]`
  - Maps known patterns to `"991.1"`, `"991.2"`, `"992.1"`, `"992.2"`, etc.
  - Examples: `"991 gen 2"` → `"991.2"`, `"992"` → `"992.1"` (if year context is absent, leave ambiguous as `None`)

- `normalize_trim(raw: str) -> Optional[str]`
  - Maps to `"CARRERA"`, `"CARRERA_S"`, `"CARRERA_4"`, `"CARRERA_4S"`, `"GTS"`, `"GTS_4"`, `"TARGA_4"`, `"TARGA_4S"`
  - Strip extra whitespace and ignore case

- `normalize_transmission(raw: str) -> Optional[str]`
  - Maps to `"PDK"` or `"MANUAL"`
  - Examples: `"pdk automatic"` → `"PDK"`, `"6-speed manual"` → `"MANUAL"`

- `normalize_body_style(raw: str) -> Optional[str]`
  - Maps to `"COUPE"`, `"CABRIOLET"`, `"TARGA"`

- `normalize_seller_type(raw: str) -> Optional[str]`
  - Maps to `"DEALER"`, `"PRIVATE"`, `"AUCTION"`, `"CPO"`

- `infer_generation_from_year(year: int, trim: Optional[str]) -> Optional[str]`
  - 2016–2019 → `"991.2"` for standard trims
  - 2020–2023 → `"992.1"` for standard trims
  - 2024+ → `"992.2"`

### 2.3 Create `app/listing_parser.py`

This module calls the Anthropic API to extract structured fields from raw listing text.

#### Prompt design rules (important):

- Send raw listing text as the user message
- System prompt must instruct the model to extract only what is explicitly stated in the text
- The model must not infer or guess values not present in the text
- Request JSON output matching the `ParsedListing` schema
- Include all field names and their expected types in the system prompt

#### Implementation steps:

1. Pre-clean the input text: strip excessive whitespace and control characters
2. Build the system prompt with the `ParsedListing` field list and extraction rules
3. Call `anthropic.Anthropic().messages.create()` with `model="claude-opus-4-7"`, structured JSON output
4. Parse the response as JSON
5. Validate the parsed JSON with `ParsedListing(**result)`
6. Run each extracted field through the corresponding normalizer function
7. Compute `missing_fields` as all fields that are `None` after parsing
8. Set `parser_confidence` based on how many required fields were extracted (year, generation, trim, body_style, transmission, mileage, asking_price are required; count filled / 7)
9. Return the validated `ParsedListing`

Required fields for confidence calculation: `year`, `generation`, `trim`, `body_style`, `transmission`, `mileage`, `asking_price`.

If the LLM call fails or returns unparseable JSON, raise an `HTTPException(status_code=502, detail="Parser error")` with the raw error logged.

### 2.4 Add `POST /api/listings/parse` route

In `app/routers/api.py`:

```python
@router.post("/listings/parse", response_model=ParsedListing)
async def parse_listing(body: ParseListingRequest):
    # body contains: raw_text: str, source_url: Optional[str]
    result = await listing_parser.parse(body.raw_text)
    return result
```

Request schema (add to `schemas.py`):

```python
class ParseListingRequest(BaseModel):
    raw_text: str
    source_url: Optional[str] = None
```

### Test gate

Send a POST request to `/api/listings/parse` with raw listing text copied from a real BaT or CnB listing page (at least 10 different listings covering different trims, transmissions, and body styles).

Verify for each listing:
- `year` is correct
- `generation` is correctly inferred or extracted
- `trim` is normalized (e.g., `"CARRERA_S"` not `"Carrera S"`)
- `transmission` is `"PDK"` or `"MANUAL"` not free text
- `body_style` is normalized
- `mileage` and `asking_price` are numeric
- `parser_confidence` is above 0.7 for clean, complete listings

---

## Piece 3 — Admin Comp Entry and Manual Seed

**Goal:** Operator can add listing comps via a web form with AI-assisted pre-fill. Seed the DB with 30–50 real comps before scrapers exist.

### 3.1 Add admin authentication middleware

In `app/routers/admin.py`, add a simple dependency that checks for an `X-Admin-Secret` header or a `?secret=` query parameter matching `settings.admin_secret`. Return `HTTP 403` if it does not match. This is not a full auth system — it is just a gate to prevent accidental public access.

### 3.2 Create `GET /admin/listings` — listing list view

Query all listings ordered by `created_at DESC`. Paginate at 50 per page using a `?page=` query param. Render `admin/listings.html`.

Template should show a table with columns: source, year, generation, trim, transmission, body_style, mileage, asking_price / sold_price, status, price_type, comp_quality, created_at. Each row links to the detail view.

### 3.3 Create `GET /admin/listings/new` — new listing form

Render `admin/listing_new.html`. The form must have:

- A large textarea for raw listing text (for AI pre-fill)
- A "Parse with AI" button that calls `POST /api/listings/parse` via HTMX and populates the form fields with the result (no full page reload)
- All editable fields from the `Listing` model: source, source_url, status, price_type, year, generation, trim, body_style, transmission, drivetrain, mileage, asking_price, sold_price, exterior_color, interior_color, location, seller_type, vin, title_status, accident_reported, owner_count, cpo, comp_quality, expert_notes
- A submit button

The HTMX "Parse with AI" button behavior:
- On click, POST the textarea content to `/api/listings/parse`
- Replace the form field values with the parsed result using `hx-swap="outerHTML"` on a form partial
- Do not replace the raw_text textarea or submit button

### 3.4 Create `POST /admin/listings` — save new listing

Accept form data from the new listing form. Validate and save as a `Listing` record. Also create an initial `PriceObservation` row:
- `observation_type = "INITIAL_ASK"` if price_type is `ASKING_PRICE`
- `observation_type = "SOLD_CONFIRMED"` if price_type is `SOLD_PRICE`
- `observed_price` = whichever of `asking_price` or `sold_price` is set
- `observed_at` = now

After saving, redirect to `GET /admin/listings/{listing_id}`.

### 3.5 Create `GET /admin/listings/{listing_id}` — listing detail and edit

Show all fields for the listing. Allow editing any field inline. Save on form submit via `POST /admin/listings/{listing_id}`. Update `updated_at` on save.

### 3.6 Create `POST /admin/listings/{listing_id}` — update listing

Accept form data. Apply updates to the existing `Listing` record. Redirect back to the detail view.

### 3.7 Seed instructions for the operator

After building the admin UI, the operator (human) should:

1. Open at least 30 real BaT sold results and CnB sold results for 991.2 and 992.1 Carrera, Carrera S, Carrera 4, Carrera 4S, and GTS in both PDK and manual transmissions.
2. For each listing: copy the listing text, open `/admin/listings/new`, paste, click "Parse with AI", correct any errors, set `source = "bat"` or `source = "cnb"`, set `price_type = "SOLD_PRICE"`, set `status = "SOLD"`, set `comp_quality = "HIGH"`, save.
3. Target mix: at least 15 confirmed sold auction comps, 10 active dealer/private asking comps, 5 CPO listings.

This seed data is required before Piece 4 (comp matching) can be tested.

### Test gate

- Open `/admin/listings/new`, paste a real listing, click "Parse with AI", verify fields populate
- Correct any fields, save — verify the record appears in `/admin/listings`
- Open the detail view — verify all fields saved correctly
- Verify the `price_observations` table has one row for the saved listing

---

## Piece 4 — Comp Matcher

**Goal:** Given a target listing, find and rank the most relevant comps from the DB.

### 4.1 Create `app/comp_matcher.py`

#### Data structures

```python
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class CompScore:
    listing_id: str
    similarity_score: float
    data_weight: float
    final_weight: float
    match_reasons: list[str]
    penalty_reasons: list[str]
```

#### Scoring function: `score_comp(target: Listing, comp: Listing) -> CompScore`

Apply the bonuses and penalties from section 2.7 of the PRD exactly:

Bonuses:
- Same generation: +25
- Same trim: +25
- Same transmission: +15
- Same body style: +10
- Mileage within 10,000 miles: +10
- Model year within 2 years: +5
- Same seller type: +3
- Same title/accident status (both clean or both flagged): +5
- Comp sold or seen within the last 12 months: +7

Penalties:
- Different generation: -30
- Different trim class: -20
- Different transmission: -15
- Accident/branded title mismatch (one has it, other does not): -15
- Modified vs stock mismatch: -10
- Mileage difference > 40,000 miles: -20
- Comp is older than 3 years: -10

Record which bonuses and penalties applied in `match_reasons` and `penalty_reasons`.

#### Data quality weights: `get_data_weight(comp: Listing) -> float`

Use the weights from section 2.8 of the PRD:
- Confirmed sold auction result (source=bat or cnb, price_type=SOLD_PRICE): 1.00
- Dealer confirmed sale (source=dealer, price_type=SOLD_PRICE): 0.80
- User-submitted sale with evidence: 0.70
- Removed listing / last-seen price: 0.40
- Active asking price: 0.25
- Stale listing (last_seen_at > 18 months ago): 0.10

#### Main function: `find_comps(target: Listing, session: Session, limit: int = 20) -> list[CompScore]`

1. Query all listings where `make = "Porsche"` and `model = "911"` and `id != target.id`
2. Score each comp using `score_comp`
3. Multiply `similarity_score * data_weight` to get `final_weight`
4. Sort by `final_weight` descending
5. Return top `limit` results

### 4.2 Add `GET /api/comps` route

```python
@router.get("/comps")
def get_comps(listing_id: str, session: Session = Depends(get_session)):
    target = session.get(Listing, UUID(listing_id))
    if not target:
        raise HTTPException(404)
    comps = comp_matcher.find_comps(target, session)
    return {"comps": comps, "target_listing_id": listing_id}
```

### Test gate

Using a known listing from the seed data (e.g., a 991.2 Carrera S PDK coupe):

- Call `GET /api/comps?listing_id={id}`
- Verify the top results are the same generation, same trim, same transmission
- Verify a comp with a different generation scores significantly lower
- Verify match_reasons and penalty_reasons are populated and accurate

---

## Piece 5 — Valuation and Report Generator

**Goal:** Generate a complete buyer report from a target listing and its comps.

### 5.1 Create `app/valuation_service.py`

#### Input

```python
@dataclass
class ValuationInput:
    target: Listing
    scored_comps: list[CompScore]
    comp_listings: dict[str, Listing]  # comp_listing_id -> Listing
```

#### Output

```python
@dataclass
class ValuationResult:
    sold_comp_low: Optional[Decimal]
    sold_comp_high: Optional[Decimal]
    sold_comp_count: int
    active_asking_low: Optional[Decimal]
    active_asking_high: Optional[Decimal]
    active_asking_count: int
    estimated_market_low: Optional[Decimal]
    estimated_market_high: Optional[Decimal]
    recommended_offer_low: Optional[Decimal]
    recommended_offer_high: Optional[Decimal]
    confidence_level: str  # HIGH, MEDIUM, LOW
    confidence_reason: str
```

#### Logic

**Sold comp range:**
- Filter `scored_comps` to those where `comp_listings[id].price_type == "SOLD_PRICE"`
- Collect `(sold_price, final_weight)` pairs
- If at least 2 sold comps exist, compute weighted 15th and 85th percentile as low/high
- If 0 or 1 sold comps, set `sold_comp_low` and `sold_comp_high` to `None`

**Active asking range:**
- Filter to comps where `price_type == "ASKING_PRICE"` and `status == "ACTIVE"`
- Use weighted 10th and 90th percentile as low/high

**Estimated market range:**
- If `sold_comp_count >= 3`: use sold range as primary. Widen by 5% if active asking data is sparse.
- If `sold_comp_count < 3` and `active_asking_count >= 3`: use active asking range, shift down by 5–8% (active asking prices are seller expectations, not clearing prices)
- If both are sparse: set to `None`

**Recommended offer range:**
- Start from `estimated_market_low` and `estimated_market_high`
- Apply adjustments:
  - Seller type is DEALER: no adjustment (dealers hold firm)
  - Seller type is PRIVATE: subtract 3–5%
  - `asking_price` > `estimated_market_high`: subtract an additional 3%
  - Confidence is LOW: widen by 5%
- Floor the offer low at `estimated_market_low - 10%`

**Confidence level:**
- HIGH: `sold_comp_count >= 5` and all top comps are same generation/trim/transmission/body
- MEDIUM: `sold_comp_count >= 2` or `active_asking_count >= 4`
- LOW: everything else (rare spec, sparse comps, heavy modifications, unusual title, missing key fields)

**Confidence reason:** Write a one-sentence string explaining the confidence level. Example: "Medium confidence: three close 991.2 Carrera S PDK coupe sold comps found, but mileage spread is wide."

### 5.2 Create `app/report_generator.py`

> **Implementation note (2026-04-29):** This section was implemented as a fully **deterministic, template-based generator** instead of an LLM call. The original plan called for Claude API here, but we pivoted to avoid the API dependency and per-report cost. All outputs (verdict, risk flags, desirability factors, seller questions, markdown narrative) are derived from the structured valuation data using rule-based logic.
>
> The LLM approach can be revisited later as an optional enhancement — a lightweight prompt that receives the same structured context and returns a richer narrative. When we do, it should be a drop-in replacement for `generate()` with an A/B toggle, not a rewrite of the pipeline.

#### Input

```python
@dataclass
class ReportInput:
    target: Listing
    valuation: ValuationResult
    top_comps: list[tuple[CompScore, Listing]]  # top 5 comps with their listings
```

#### Output

```python
@dataclass
class ReportOutput:
    verdict: str
    risk_flags: list[str]
    desirability_factors: list[str]
    seller_questions: list[str]
    report_markdown: str
```

#### Deterministic logic

- **verdict**: derived from `asking_price` vs `estimated_market_low/high` thresholds (e.g. asking < low * 0.95 → "Strong value", asking > high * 1.15 → "Significantly overpriced")
- **risk_flags**: from `accident_reported`, `title_status`, `owner_count`, `mileage`, `modifications`, `seller_type`, and confidence level
- **desirability_factors**: from `transmission == MANUAL`, `cpo`, low mileage, clean title, notable options (Sport Chrono, PCCB, PTS, etc.), GT/Turbo trim
- **seller_questions**: triggered by missing data, accidents, modifications, high mileage, manual transmission, and low confidence
- **report_markdown**: Python f-string template assembling all sections (Summary, Market Context, Comps Used, Desirability, Risk Flags, Deal Advice)

### 5.3 Add `POST /api/reports/generate` route

```python
@router.post("/reports/generate")
def generate_report(body: GenerateReportRequest, session: Session = Depends(get_session)):
    # body: { listing_id: str }
    target = session.get(Listing, UUID(body.listing_id))
    if not target:
        raise HTTPException(404)

    # 1. Find comps
    comp_scores = comp_matcher.find_comps(target, session, limit=20)
    comp_listings = {str(cs.listing_id): session.get(Listing, cs.listing_id) for cs in comp_scores}

    # 2. Compute valuation
    valuation = valuation_service.compute(ValuationInput(target, comp_scores, comp_listings))

    # 3. Generate report
    top_comps = [(comp_scores[i], comp_listings[str(comp_scores[i].listing_id)]) for i in range(min(5, len(comp_scores)))]
    report_output = report_generator.generate(ReportInput(target, valuation, top_comps))

    # 4. Persist report
    report = Report(
        target_listing_id=target.id,
        verdict=report_output.verdict,
        confidence_level=valuation.confidence_level,
        asking_price=target.asking_price,
        estimated_low=valuation.estimated_market_low,
        estimated_high=valuation.estimated_market_high,
        recommended_offer_low=valuation.recommended_offer_low,
        recommended_offer_high=valuation.recommended_offer_high,
        sold_comp_summary={"count": valuation.sold_comp_count, "low": str(valuation.sold_comp_low), "high": str(valuation.sold_comp_high)},
        active_comp_summary={"count": valuation.active_asking_count, "low": str(valuation.active_asking_low), "high": str(valuation.active_asking_high)},
        risk_flags={"flags": report_output.risk_flags},
        desirability_factors={"factors": report_output.desirability_factors},
        seller_questions={"questions": report_output.seller_questions},
        report_markdown=report_output.report_markdown,
    )
    session.add(report)

    # 5. Persist comp matches
    for cs in comp_scores[:10]:
        match = CompMatch(
            report_id=report.id,
            comp_listing_id=cs.listing_id,
            similarity_score=Decimal(str(cs.similarity_score)),
            data_weight=Decimal(str(cs.data_weight)),
            final_weight=Decimal(str(cs.final_weight)),
            match_reason={"bonuses": cs.match_reasons, "penalties": cs.penalty_reasons},
        )
        session.add(match)

    session.commit()
    session.refresh(report)

    return {"report_id": str(report.id)}
```

### 5.4 Add `GET /reports/{report_id}` public page

Query the `Report` by ID. Query the `CompMatch` rows for this report. Query the comp `Listing` records. Render `report.html`.

The report template must display:
- Verdict (prominent, styled by verdict type)
- Asking price
- Estimated market range (low–high)
- Recommended offer range (low–high)
- Confidence level with reason
- Sold comp range and count
- Active asking range and count
- Top 5 comps as cards (year, trim, transmission, mileage, price, source, similarity score)
- Desirability factors as bullet list
- Risk flags as bullet list (styled in a warning color)
- Questions to ask the seller as bullet list
- Full report markdown rendered as HTML

### 5.5 Add report to admin

In `app/routers/admin.py`, add `GET /admin/reports` that lists all reports with: report_id, target listing summary, verdict, confidence_level, created_at. Link to the public report page.

### Test gate

1. With the seed comp data from Piece 3, pick one of the seed listings as a target
2. Call `POST /api/reports/generate` with its `listing_id`
3. Open `GET /reports/{report_id}` and verify all sections render
4. Manually verify the estimated market range makes sense given the seed comps
5. Check the report markdown contains no invented prices or comps

---

## Piece 6 — Public Submit UI

**Goal:** A user can paste a URL or listing text and receive a report.

### 6.1 Update `GET /submit`

Render `submit.html`. The form contains:
- A URL input field (optional)
- A large textarea for listing text
- An optional asking price override (number input)
- An optional mileage override (number input)
- A notes field
- A submit button labeled "Analyze this listing"

### 6.2 Update `POST /submit`

1. Accept the form fields
2. If a URL is provided, check the `scraper_registry` for a matching scraper. If no scraper matches, fall through to the AI parser.
3. If falling through to AI parser: use the pasted text
4. If pasted text is also empty: return an error asking the user to provide either a URL or pasted text
5. Apply any price or mileage overrides to the parsed listing
6. Save a new `Listing` record with `source = "user_submitted"` and `status = "ACTIVE"`
7. Call `POST /api/reports/generate` internally (not via HTTP, call the function directly)
8. Redirect to `GET /reports/{report_id}`

At this stage, the scraper_registry can return "no scraper found" for all URLs — that is expected. The AI parser path handles everything.

### 6.3 Add email capture to the submit result

On the report page, below the report, add a section: "Get notified when new 911s match your search." Include an email input and a "Notify me" button. For now, the button should just call `POST /api/email-capture` with the email and report_id and return a success message. Store the email and report_id in a simple `email_captures` table (add to models.py and create a migration).

```python
class EmailCapture(SQLModel, table=True):
    __tablename__ = "email_captures"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str
    report_id: Optional[uuid.UUID] = Field(default=None, foreign_key="reports.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### Test gate

1. Open `/submit` in a browser
2. Paste a real BaT listing text (no URL scraping needed yet)
3. Click "Analyze this listing"
4. Verify redirect to report page with all sections populated
5. Enter an email and click "Notify me" — verify the email_captures table has the row

---

## Piece 7 — BaT Scraper

**Goal:** Fetch Bring a Trailer listing pages and parse them into `ParsedListing` without the AI parser.

### 7.1 Create `app/scrapers/registry.py`

```python
from typing import Optional
from app.schemas import ParsedListing

def get_scraper(url: str):
    if "bringatrailer.com" in url:
        from app.scrapers.bat import BaTScraper
        return BaTScraper()
    if "carsandbids.com" in url:
        from app.scrapers.cnb import CnBScraper
        return CnBScraper()
    return None

async def scrape(url: str) -> Optional[ParsedListing]:
    scraper = get_scraper(url)
    if scraper is None:
        return None
    return await scraper.scrape(url)
```

### 7.2 Create `app/scrapers/bat.py`

The BaT scraper must:

1. Fetch the listing page HTML using `httpx.AsyncClient` with a descriptive `User-Agent` header (e.g., `"911DealRadar/1.0 (research; contact@example.com)"`) and a 10-second timeout
2. Check the HTTP status code — if 403, 429, or 503, log a restriction event and return `None`
3. Parse the HTML with `BeautifulSoup` (`uv add beautifulsoup4 lxml`)
4. Extract structured listing fields from BaT's HTML structure (title, year/make/model, mileage, bid/sold price, transmission, body style, seller, location, options listed in the description)
5. Extract the sold price from the "sold for" badge if present; mark `price_type = "SOLD_PRICE"` and `status = "SOLD"`
6. Extract the current bid if auction is active; mark `price_type = "BID_TO_PRICE"` and `status = "ACTIVE"`
7. Extract listed options from the options section of the page if present
8. Run all extracted values through the normalizer
9. Store the raw HTML snapshot in `raw_text`
10. Return a `ParsedListing`

Restriction logging: for every blocked or degraded fetch, emit a structured log entry with source, url, timestamp, http_status, restriction_signal, headers excerpt. Use Python `logging` with a `JSON`-formatted log record. Do not raise exceptions for restriction events — return `None` and log.

Rate limiting: add a 1–2 second `asyncio.sleep` between requests within a scraper session. Never send concurrent requests to the same domain.

### 7.3 Update `POST /submit` to use the scraper

In `public.py`, update the submit handler:
- If a URL is provided, call `scraper_registry.scrape(url)` first
- If it returns a `ParsedListing`, use it directly (skip the AI parser)
- If it returns `None`, fall through to the AI parser with the pasted text

### 7.4 Add a BaT batch ingestion script

Create `scripts/ingest_bat.py`. This script:
1. Accepts a list of BaT listing URLs via stdin or a text file
2. For each URL, calls the BaT scraper
3. Saves the result as a `Listing` record
4. Prints a summary of how many succeeded, how many were blocked, how many failed to parse

Run: `uv run python scripts/ingest_bat.py < bat_urls.txt`

### Test gate

1. Call `scripts/ingest_bat.py` with 50 BaT sold result URLs
2. Inspect the resulting `Listing` rows in the DB
3. Compare auto-parsed fields against the actual listing page
4. Measure: what percentage of rows have generation, trim, and transmission correctly extracted?
5. Target: >80% for those three fields without AI parser fallback

---

## Piece 8 — Cars and Bids Scraper

> **SKIPPED (2026-04-29):** Investigation showed that CnB does not expose sold prices or asking prices in a reliably accessible way — the OG title only gives year/trim/body/drivetrain, and sold prices are behind their data layer. A listing without a price has no value as a comp, so ingesting CnB data would add noise without improving valuation quality.
>
> Revisit only if a reliable method to extract CnB sold prices is found (e.g. a public API, structured JSON embed, or accessible DOM element on completed auction pages).

---

## Piece 9 — CPO and Dealer Aggregator Scrapers with Scheduled Refresh

**Goal:** Capture active asking prices from Porsche CPO and major dealer aggregators. Refresh on a schedule.

### 9.1 Create `app/scrapers/cpo.py`

Scrape Porsche's CPO inventory search page:
- Fetch the public CPO inventory listing results
- Extract each listed vehicle's year, trim, mileage, asking price, location, and VIN if available
- Mark `price_type = "ASKING_PRICE"`, `status = "ACTIVE"`, `seller_type = "CPO"`, `cpo = True`
- Run through normalizer
- For each vehicle, check if a `Listing` with the same VIN or source_url already exists — if yes, create a `PriceObservation` row instead of a new `Listing`

### 9.2 Create `app/scrapers/aggregators.py`

Implement scrapers for AutoTrader, Cars.com, and CarGurus 911 search result pages:
- Each scraper follows the same restriction-logging pattern
- Only attempt to scrape if the page does not require authentication or CAPTCHA
- If blocked, log the restriction event and return an empty list (do not retry in the same run)
- Mark `price_type = "ASKING_PRICE"`, `status = "ACTIVE"`, `seller_type = "DEALER"`

### 9.3 Create a scheduled refresh job

Create `scripts/refresh_listings.py`:
1. For each ACTIVE listing in the DB, re-fetch its source_url
2. Compare the current asking price to the last-seen price
3. If price dropped: create a `PriceObservation` with `observation_type = "PRICE_DROP"`
4. If listing is no longer found (404 or removed): update `status = "REMOVED_UNKNOWN"`, create `PriceObservation` with `observation_type = "REMOVED"`
5. If listing is found at same price: create `PriceObservation` with `observation_type = "LAST_SEEN"`
6. Log per-source restriction events

Use APScheduler to run this script on a schedule (e.g., every 6 hours):

```python
from apscheduler.schedulers.blocking import BlockingScheduler
scheduler = BlockingScheduler()
scheduler.add_job(refresh_all_sources, 'interval', hours=6)
scheduler.start()
```

Add `apscheduler` to dependencies: `uv add apscheduler`.

### 9.4 Add per-source health to admin

In `/admin/listings`, add a "Source Health" section showing a table:
- Source name
- Total records
- ACTIVE count
- SOLD count
- Restriction event count (last 7 days)
- Most recent successful scrape timestamp

Query the logs table or a new `scraper_events` table for this. Add a `ScrapeEvent` model:

```python
class ScrapeEvent(SQLModel, table=True):
    __tablename__ = "scrape_events"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source: str
    url: Optional[str] = None
    run_id: str
    http_status: Optional[int] = None
    restriction_signal: Optional[str] = None  # RATE_LIMIT, CAPTCHA, IP_BLOCK, STRUCTURAL_CHANGE, etc.
    success: bool
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### Test gate

1. Run `scripts/refresh_listings.py` manually
2. Verify `price_observation` rows are created for all ACTIVE listings
3. Verify `ScrapeEvent` rows are created for every scraper run
4. Open `/admin/listings` and verify the Source Health table shows accurate counts and restriction events
5. Intentionally provide a dead URL and verify it produces a `REMOVED` observation

---

## Piece 10 — Seed Validation and Tuning

**Goal:** Confirm data volume and quality targets. Tune matching and valuation until reports are trustworthy.

### 10.1 Validate comp dataset volume

Run the following SQL queries and confirm targets are met:

```sql
-- Total comps
SELECT COUNT(*) FROM listings WHERE make = 'Porsche' AND model = '911';

-- By price type
SELECT price_type, COUNT(*) FROM listings GROUP BY price_type;

-- Confirmed sold
SELECT COUNT(*) FROM listings WHERE price_type = 'SOLD_PRICE';

-- By generation
SELECT generation, COUNT(*) FROM listings GROUP BY generation;

-- By trim
SELECT trim, generation, COUNT(*) FROM listings GROUP BY trim, generation ORDER BY COUNT(*) DESC;
```

Targets from section 2.13 of the PRD:
- 800+ confirmed sold comps (price_type = SOLD_PRICE)
- 800+ active asking listings (price_type = ASKING_PRICE, status = ACTIVE)
- 300+ historical/removed listings

If targets are not met, run additional batch ingestion against BaT and CnB archives.

### 10.2 Generate test reports

Select one listing from each of the following spec buckets and generate a report:
- 991.2 Carrera S PDK Coupe
- 991.2 Carrera S Manual Coupe
- 991.2 Carrera 4S PDK
- 991.2 GTS Manual Coupe
- 992.1 Carrera S PDK Coupe
- 992.1 Carrera 4S PDK

For each generated report, record:
- Number of comps found
- Number of sold comps
- Confidence level
- Whether the estimated market range seems plausible

### 10.3 Tune similarity scoring

If reports are returning too few close comps, reduce penalties for minor mismatches. If reports are returning irrelevant comps, increase penalties for generation and trim mismatches. Document any changes to the scoring weights as inline comments with the reason.

### 10.4 Tune valuation weighting

If the estimated market range is too wide (> 20% spread), check whether stale or low-quality comps are pulling the range apart. Lower the weight for comps with `comp_quality = "LOW"` or `last_seen_at` older than 18 months.

### 10.5 Confidence distribution check

Run this query:
```sql
SELECT confidence_level, COUNT(*) FROM reports GROUP BY confidence_level;
```

If more than 50% of reports are LOW confidence, the comp dataset is still too sparse or the confidence thresholds are too strict. Adjust the thresholds in `valuation_service.py` and document the change.

### Test gate

- At least 5 of the 6 spec-bucket reports have confidence MEDIUM or HIGH
- All reports show a plausible estimated market range (validate manually against your own knowledge of these car values)
- No report contains invented data (spot-check the LLM output against the comps used)
- The admin `/admin/reports` page shows all generated reports

---

## Piece 11 — Cloud Migration (post local testing)

**Goal:** Move from local Docker to a hosted environment so the scheduled refresh runs automatically, the database is persisted in the cloud, and the app has a real public URL.

**Trigger:** Complete Piece 10 (seed validation) locally first. Migrate once comp data and report quality are confirmed good.

### What to migrate

1. **App hosting** — Deploy the FastAPI app to a cloud service. Good options for this stack:
   - [Railway](https://railway.app) — simplest; supports Docker deploys, managed Postgres, and built-in cron jobs. Recommended.
   - [Render](https://render.com) — similar; free tier available but Postgres has a 90-day expiry on free plan.
   - [Fly.io](https://fly.io) — more control; requires a `fly.toml` config file.

2. **Managed PostgreSQL** — Provision a managed Postgres instance (Railway/Render both offer this as an add-on). Update `DATABASE_URL` in the cloud service's environment variables. Run `alembic upgrade head` against the cloud DB before first deploy.

3. **Scheduled refresh** — Replace the standalone `scripts/refresh.py --once` manual invocation with a scheduled job. Options:
   - **Railway cron job**: Add a separate cron service in Railway that runs `python scripts/refresh.py --once` on a schedule (e.g., every 12 hours). Railway cron services share the same repo and env vars.
   - **In-process scheduler**: Wire APScheduler into the FastAPI app startup event so it runs automatically when the app is running:
     ```python
     # In app/main.py — add a startup event
     from apscheduler.schedulers.asyncio import AsyncIOScheduler
     from scripts.refresh import run_refresh

     scheduler = AsyncIOScheduler()

     @app.on_event("startup")
     async def start_scheduler():
         scheduler.add_job(run_refresh, "interval", hours=12, id="refresh")
         scheduler.start()

     @app.on_event("shutdown")
     async def stop_scheduler():
         scheduler.shutdown()
     ```
   - **External cron (GitHub Actions)**: Add a `.github/workflows/refresh.yml` workflow that triggers on a schedule and calls a protected `/api/admin/refresh` endpoint. Simpler to set up but adds a GitHub Actions dependency.

4. **Public URL** — The cloud service will provide a URL (e.g., `https://911-deal-radar.up.railway.app`). This is used to share report links and to wire up any future webhooks or email links.

### Checklist before migrating

- [ ] At least 800 confirmed sold comps in DB (Piece 10.1 targets met)
- [ ] Test reports generate at HIGH or MEDIUM confidence for all 6 spec buckets (Piece 10.2)
- [ ] `alembic upgrade head` tested on a clean DB (not just local Docker)
- [ ] `ADMIN_SECRET` set to a non-default value in cloud env vars
- [ ] `.env` file not committed (`.gitignore` check)
- [ ] `ANTHROPIC_API_KEY` set as a secret env var in the cloud service, not hardcoded

### Key invariants that carry forward

- `DATABASE_URL` must point to the cloud Postgres instance (not localhost)
- The scheduled refresh must survive app restarts — APScheduler in-process does not persist state; if using Railway cron, it is independent of app uptime
- Report URLs (`/reports/{id}`) will be permanent once live — do not change the UUID-based routing scheme

---

## Appendix: Environment Variable Reference

| Variable | Description | Example |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+psycopg://dealradar:dealradar@localhost:5432/dealradar` |
| `ANTHROPIC_API_KEY` | Anthropic API key for LLM calls | `sk-ant-...` |
| `ADMIN_SECRET` | Simple secret for admin route access | `change_me_in_prod` |

---

## Appendix: Running Locally

```bash
# Start DB and app
docker-compose up

# Or run app only (DB must be running separately)
uv run uvicorn app.main:app --reload

# Apply migrations
uv run alembic upgrade head

# Generate a new migration after model changes
uv run alembic revision --autogenerate -m "description"

# Run batch ingestion
uv run python scripts/ingest_bat.py < bat_urls.txt
uv run python scripts/ingest_cnb.py < cnb_urls.txt

# Run scheduled refresh manually
uv run python scripts/refresh_listings.py
```

---

## Appendix: Key Invariants for AI Agents

1. The LLM must never invent prices, mileage, comps, or risk flags not present in the structured data passed to it.
2. Scrapers must never bypass CAPTCHAs, login walls, or pages that require an account.
3. Every scraper run must log a `ScrapeEvent` record regardless of success or failure.
4. Every `Listing` save must produce at least one `PriceObservation` row.
5. Active listing prices are seller expectations, not transaction prices — always label them separately in the UI and reports.
6. Admin routes must always check the `admin_secret` before executing any query or mutation.
7. Never store sensitive user data beyond email address and report association.
8. All monetary values must use `Decimal`, never `float`, to avoid floating-point precision errors.
