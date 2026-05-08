# 911 Deal Radar — Execution Plan v2

This document covers the next phase of features after the MVP is live and functional. Each piece is sequenced by dependency and impact.

---

## Piece A — Additional Data Sources

### A.1 New scraper targets

Add scrapers for the following sources. Each follows the same restriction-logging pattern (`ScrapeEvent`) as the existing BaT and CarGurus scrapers.

**Sold / auction sources (high data quality):**
- **Cars and Bids** (`carsandbids.com`) — revisit; check if sold prices are now accessible via their listing JSON embed or a structured data endpoint. If extractable, treat same as BaT (data_weight 1.0).
- **PCarMarket** (`pcarmarket.com`) — Porsche-specific auction site, strong comp quality.

**Active asking sources:**
- **Autotrader** (`autotrader.com`) — large dealer inventory; likely bot-protected, test first.
- **Cars.com** — similar to Autotrader.
- **Porsche dealer inventory pages** — individual dealer sites vary; consider a curated list of the top 10 CPO dealers by volume.

### A.2 Accept more URLs in /submit

Update `app/routers/public.py` submit handler to recognize and route:
- `carsandbids.com` → CnB scraper (once A.1 is done)
- `pcarmarket.com` → PCarMarket scraper
- `autotrader.com` → fall through to AI parser (fetch + strip HTML)
- `cars.com` → fall through to AI parser
- Any unrecognized URL → attempt HTML fetch + AI parser, show bot-protection error if blocked

Update source label logic (currently only BaT/CarGurus/CnB are named) to include all new sources.

### A.3 Refresh integration

Add each new scraper to `scripts/refresh.py` following the same pattern as `refresh_bat()` and `refresh_cargurus()`. Schedule per-source at appropriate cadence (sold auction sources: daily; active asking: every 12 hours).

---

## Piece B — AI Listing Parser with Rate Limiting

The Claude API is already wired up for listing text parsing. This piece adds guardrails to prevent abuse.

### B.1 Per-IP rate limiting

Add a rate limit dependency on `POST /submit`:
- Max 5 submissions per IP per hour
- Max 20 submissions per IP per day
- Store counters in a lightweight in-memory store (e.g. `slowapi` with an in-memory backend) or a Redis-backed store if available
- On limit hit: return a 429 response with a friendly HTML error page (not a JSON error)

Recommended library: `slowapi` (wraps `limits`, integrates cleanly with FastAPI).

```
uv add slowapi
```

### B.2 Input validation before AI call

Before sending text to Claude:
- Reject inputs shorter than 50 characters (not a real listing)
- Reject inputs longer than 20,000 characters (truncate or reject)
- Check for obvious non-listing patterns (e.g. input is all punctuation, all numbers, etc.)
- If the AI parser returns a listing with `parser_confidence < 0.3`, show a helpful error rather than saving a junk record

### B.3 Token usage logging

Log token usage per call to a `ai_usage_events` table:
```python
class AIUsageEvent(SQLModel, table=True):
    __tablename__ = "ai_usage_events"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    endpoint: str           # "listing_parse"
    input_tokens: int
    output_tokens: int
    source_ip: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

Add a daily token budget cap. If cumulative daily usage exceeds threshold (e.g. 500k tokens/day), disable AI parsing and return a "service temporarily unavailable" message. Check and enforce in the rate limit dependency.

### B.4 Admin visibility

Add token usage summary to `/admin` landing page: today's token count, this month's count, and a warning if approaching the daily cap.

---

## Piece C — Email Notifications

### C.1 Email infrastructure

Choose and integrate a transactional email provider:
- **Resend** (`resend.com`) — recommended; simple API, generous free tier (3,000 emails/month), good Python SDK
- Alternative: SendGrid, Postmark

```
uv add resend
```

Add `RESEND_API_KEY` to `app/config.py` and Fly secrets.

### C.2 Match detection logic

Create `scripts/notify.py` with a `find_matches()` function:

For each `EmailCapture` row that has at least an email:
1. Filter active listings where `generation == trim_interest` (if specified) and `asking_price` is within `budget_min`–`budget_max` (if specified)
2. For each match, check if we've already notified this subscriber about this listing (see C.3)
3. Collect new matches not yet notified

### C.3 Notification tracking

Add a `NotificationSent` table to avoid duplicate emails:
```python
class NotificationSent(SQLModel, table=True):
    __tablename__ = "notifications_sent"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email_capture_id: uuid.UUID = Field(foreign_key="email_captures.id")
    listing_id: uuid.UUID = Field(foreign_key="listings.id")
    sent_at: datetime = Field(default_factory=datetime.utcnow)
```

### C.4 Email template

Design a plain-text-first email (HTML version optional for v1):
- Subject: `New 911 match: [year] [trim] [generation] — $[price]`
- Body: key listing details, estimated market range (run the valuation inline), link to submit the listing for a full report
- Footer: unsubscribe link (one-click, token-based)

### C.5 Unsubscribe

Add `GET /unsubscribe?token={token}` public route. Token is `hmac(email_capture_id, secret)`. On valid token: mark `EmailCapture.unsubscribed = True` (add column + migration). Exclude unsubscribed rows from all notification queries.

### C.6 Scheduling

Add `notify_subscribers` to `scripts/refresh.py` run cycle — fire once per day after the refresh completes. Configurable frequency: start weekly, move to daily once list grows.

---

## Piece D — UI/UX Redesign

### D.1 Design direction

Porsche 911 enthusiast aesthetic:
- **Color palette**: black (#0A0A0A) as primary, Porsche Guards Red (#D5001C) as accent, light warm grey (#F5F4F0) as background, white for cards
- **Typography**: use `Inter` or `DM Sans` from Google Fonts (free, clean, modern); consider a bold serif or condensed font for hero headings
- **Imagery**: subtle 911 silhouette or side-profile line art as hero background on index (SVG, no stock photos)
- **Tone**: confident, data-driven, enthusiast — not generic SaaS

### D.2 Landing page (`index.html`)

Rebuild with:
- Full-width hero section: headline ("Know if it's a deal before you buy"), sub-headline, single CTA button ("Analyze a listing")
- Below fold: three feature callouts with icons (Comp Data, Valuation, Risk Flags)
- A sample report preview section (static screenshot or live embedded example)
- Minimal footer with tagline

### D.3 Submit page (`submit.html`)

- Cleaner single-column layout
- URL input as the primary action (large, prominent)
- "Or paste listing text" as a secondary collapsible section
- Loading state while report generates (spinner + "Analyzing…" copy)

### D.4 Report page (`report.html`)

- Verdict displayed as a large badge with color coding (green = deal, red = overpriced, grey = insufficient data)
- Price comparison shown as a visual range bar (asking price dot plotted on estimated low–high range) — pure CSS/HTML, no JS library needed
- Comp cards redesigned: cleaner layout, show sold vs active badge, source logo/label
- Risk flags in a styled warning card (amber border)
- Desirability factors in a styled positive card (green border)
- Overall page feels like a premium car research tool, not a form result

### D.5 Admin pages

Admin pages can stay functional/minimal — they are internal only. Minor cleanup only (consistent nav, sign-out button visible on all pages).

---

## Sequencing recommendation

| Order | Piece | Reason |
|---|---|---|
| 1 | B (Rate limiting) | Protects the live site before sharing widely |
| 2 | D (UI redesign) | Makes the site shareable and builds credibility |
| 3 | A (More data sources) | Improves report quality and comp coverage |
| 4 | C (Email notifications) | Requires a healthy subscriber list to be worthwhile |
