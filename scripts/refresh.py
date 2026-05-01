"""
Scheduled data refresh — fetches the most recent sold/active 911 listings
from BaT and CarGurus, deduplicates, and saves new rows to the DB.

Runs immediately on startup, then every 12 hours.

Usage:
    uv run python scripts/refresh.py           # continuous mode (every 12h)
    uv run python scripts/refresh.py --once    # run once and exit
"""

import asyncio
import json
import logging
import re
import sys
import time
import uuid
from argparse import ArgumentParser
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine
from app.models import Listing, ScrapeEvent
from app.normalizer import infer_generation_from_year, normalize_body_style, normalize_trim
from app.scrapers.bat import scrape as bat_scrape

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

BAT_HEADERS = {"User-Agent": "911DealRadar/1.0 (research; wei.zeng1993@gmail.com)"}
CG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

BAT_API_URL = (
    "https://bringatrailer.com/wp-json/bringatrailer/1.0/data/listings-filter"
    "?page={page}&per_page=36&get_items=1&get_stats=0&sort=td"
    "&location%5B%5D=US&include_s=911&state=sold"
)

CG_BASE_URL = (
    "https://www.cargurus.com/search"
    "?sourceContext=carGurusHomePageModel"
    "&makeModelTrimPaths=m48%2Cm48%2Fd404"
    "&isDeliveryEnabled=true"
    "&priceDropsOnly=false"
    "&distance=100"
    "&sortDirection=ASC"
    "&sortType=BEST_MATCH"
    "&startYear=2016"
    "&endYear=2019"
    "&vehicleHistoryOptions=CLEAN_TITLE%2CUNDAMAGED_FRAME%2CNO_THEFT_HISTORY%2CLEMON_FREE%2CNON_SALVAGE"
    "&zip={zip}"
    "&startIndex=0"
)

# One representative zip per metro — refresh only needs a current snapshot
METRO_ZIPS = {
    "SF Bay Area":    "94102",
    "Los Angeles":    "90001",
    "New Jersey":     "07101",
    "Dallas":         "75201",
    "Houston":        "77001",
    "Seattle":        "98101",
    "Portland":       "97201",
    "Salt Lake City": "84101",
    "Phoenix":        "85001",
    "Tucson":         "85701",
}

CG_MIN_PRICE = 50_000
CG_MAX_PRICE = 600_000
CG_VALID_YEARS = range(2016, 2020)


def _load_existing(session: Session) -> tuple[set[str], set[str]]:
    vins = set(session.exec(select(Listing.vin).where(Listing.vin.isnot(None))).all())
    urls = set(session.exec(select(Listing.source_url).where(Listing.source_url.isnot(None))).all())
    return vins, urls


# ---------------------------------------------------------------------------
# BaT refresh — latest 3 pages of sold 911 listings (~100 items)
# ---------------------------------------------------------------------------

async def refresh_bat() -> int:
    """Fetch the 3 most recent pages of sold 911 listings from BaT, save new ones."""
    logger.info("[BaT] Starting refresh (3 pages × 36 = up to 108 listings)")
    run_id = str(uuid.uuid4())

    # Discover URLs via API
    new_urls: list[str] = []
    async with httpx.AsyncClient(headers=BAT_HEADERS, timeout=15, follow_redirects=True) as client:
        for page in range(1, 4):
            try:
                r = await client.get(BAT_API_URL.format(page=page))
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.error("[BaT] API page %d failed: %s", page, e)
                break

            items = data.get("items", [])
            page_urls = [
                item["url"]
                for item in items
                if "porsche 911" in item.get("title", "").lower() and item.get("url")
            ]
            logger.info("[BaT] API page %d: %d Porsche 911 URLs", page, len(page_urls))
            new_urls.extend(page_urls)
            await asyncio.sleep(1)

    new_urls = list(dict.fromkeys(new_urls))

    with Session(engine) as session:
        existing_vins, existing_urls = _load_existing(session)

    saved = 0
    skipped = 0

    for i, url in enumerate(new_urls, 1):
        if url in existing_urls:
            skipped += 1
            continue

        parsed, http_status, restriction_signal = await bat_scrape(url)

        with Session(engine) as session:
            session.add(ScrapeEvent(
                source="bringatrailer",
                url=url,
                run_id=run_id,
                http_status=http_status,
                restriction_signal=restriction_signal,
                success=parsed is not None,
            ))
            session.commit()

        if parsed is None or not parsed.year or (not parsed.sold_price and not parsed.asking_price):
            continue
        if not parsed.trim:
            continue
        if parsed.vin and parsed.vin in existing_vins:
            skipped += 1
            continue

        price_type = "SOLD_PRICE" if parsed.sold_price else "BID_TO_PRICE"
        status = "SOLD" if parsed.sold_price else "ACTIVE"

        listing = Listing(
            source="bringatrailer",
            source_url=url,
            status=status,
            price_type=price_type,
            asking_price=parsed.asking_price,
            sold_price=parsed.sold_price,
            year=parsed.year,
            make="Porsche",
            model="911",
            generation=parsed.generation,
            trim=parsed.trim,
            body_style=parsed.body_style,
            transmission=parsed.transmission,
            drivetrain=parsed.drivetrain,
            mileage=parsed.mileage,
            exterior_color=parsed.exterior_color,
            interior_color=parsed.interior_color,
            location=parsed.location,
            seller_type=parsed.seller_type,
            vin=parsed.vin,
            title_status=parsed.title_status,
            accident_reported=parsed.accident_reported,
            owner_count=parsed.owner_count,
            cpo=parsed.cpo,
            options=parsed.options or None,
            modifications=parsed.modifications or None,
            confidence_score=Decimal(str(parsed.parser_confidence)),
            date_seen=datetime.utcnow(),
            date_sold=datetime.utcnow() if parsed.sold_price else None,
        )
        with Session(engine) as session:
            session.add(listing)
            session.commit()

        if parsed.vin:
            existing_vins.add(parsed.vin)
        existing_urls.add(url)
        saved += 1
        logger.info(
            "[BaT] Saved: %s %s %s | sold $%s",
            parsed.year, parsed.trim, parsed.body_style or "",
            f"{parsed.sold_price:,.0f}" if parsed.sold_price else "N/A",
        )

    logger.info("[BaT] Done — saved: %d, skipped (dup): %d", saved, skipped)
    return saved


# ---------------------------------------------------------------------------
# CarGurus refresh — first page of active listings per metro
# ---------------------------------------------------------------------------

def _extract_cg_listings(html: str) -> list[dict]:
    match = re.search(
        r'__remixContext\.r\("routes/[^"]+",\s*"recommendations",\s*(\[.+?\])\)',
        html,
        re.DOTALL,
    )
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return []


def _cg_raw_to_listing(raw: dict) -> Optional[Listing]:
    year = raw.get("year")
    if not year or year not in CG_VALID_YEARS:
        return None
    price = raw.get("price")
    if not price or not (CG_MIN_PRICE <= price <= CG_MAX_PRICE):
        return None

    trim_str = raw.get("trim", "")
    listing_id = raw.get("listingId", "")

    return Listing(
        source="cargurus",
        source_url=f"https://www.cargurus.com/Cars/new/nl/d404#listing={listing_id}",
        status="ACTIVE",
        price_type="ASKING_PRICE",
        asking_price=Decimal(str(price)),
        year=year,
        make="Porsche",
        model="911",
        generation=infer_generation_from_year(year),
        trim=normalize_trim(trim_str),
        body_style=normalize_body_style(trim_str),
        drivetrain="AWD" if "AWD" in trim_str else ("RWD" if "RWD" in trim_str else None),
        mileage=raw.get("mileage"),
        exterior_color=raw.get("exteriorColor"),
        location=raw.get("cityRegion"),
        seller_type="DEALER" if raw.get("sellerType") == "DEALER" else "PRIVATE",
        vin=raw.get("vin"),
        date_seen=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
    )


def refresh_cargurus() -> int:
    """Fetch one page of active 991.2 listings per metro, save new ones."""
    logger.info("[CarGurus] Starting refresh (%d metros)", len(METRO_ZIPS))
    run_id = str(uuid.uuid4())

    with Session(engine) as session:
        existing_vins, existing_urls = _load_existing(session)

    saved = 0
    skipped = 0

    with httpx.Client(headers=CG_HEADERS) as client:
        for metro, zip_code in METRO_ZIPS.items():
            url = CG_BASE_URL.format(zip=zip_code)
            http_status = None
            restriction_signal = None
            success = False
            try:
                r = client.get(url, timeout=20, follow_redirects=True)
                http_status = r.status_code
            except Exception as e:
                logger.error("[CarGurus] Fetch error %s: %s", metro, e)
                restriction_signal = "NETWORK_ERROR"
                with Session(engine) as session:
                    session.add(ScrapeEvent(
                        source="cargurus",
                        url=url,
                        run_id=run_id,
                        http_status=None,
                        restriction_signal=restriction_signal,
                        success=False,
                    ))
                    session.commit()
                time.sleep(3)
                continue

            if r.status_code == 403:
                restriction_signal = "IP_BLOCK"
            elif r.status_code == 429:
                restriction_signal = "RATE_LIMIT"
            elif r.status_code != 200:
                restriction_signal = "STRUCTURAL_CHANGE"

            if r.status_code != 200:
                logger.warning("[CarGurus] %s returned %d", metro, r.status_code)
                with Session(engine) as session:
                    session.add(ScrapeEvent(
                        source="cargurus",
                        url=url,
                        run_id=run_id,
                        http_status=http_status,
                        restriction_signal=restriction_signal,
                        success=False,
                    ))
                    session.commit()
                continue

            raw_listings = _extract_cg_listings(r.text)
            metro_new = 0

            with Session(engine) as session:
                session.add(ScrapeEvent(
                    source="cargurus",
                    url=url,
                    run_id=run_id,
                    http_status=http_status,
                    restriction_signal=None,
                    success=True,
                ))

                for raw in raw_listings:
                    vin = raw.get("vin")
                    if vin and vin in existing_vins:
                        skipped += 1
                        continue

                    listing = _cg_raw_to_listing(raw)
                    if listing is None:
                        continue

                    session.add(listing)
                    session.flush()

                    if vin:
                        existing_vins.add(vin)
                    existing_urls.add(listing.source_url or "")
                    saved += 1
                    metro_new += 1

                session.commit()

            logger.info("[CarGurus] %s: +%d new listings (%d on page)", metro, metro_new, len(raw_listings))
            time.sleep(2)

    logger.info("[CarGurus] Done — saved: %d, skipped (dup): %d", saved, skipped)
    return saved


# ---------------------------------------------------------------------------
# Combined refresh job
# ---------------------------------------------------------------------------

async def run_refresh() -> None:
    start = datetime.utcnow()
    logger.info("=== Refresh started at %s ===", start.strftime("%Y-%m-%d %H:%M UTC"))

    bat_saved = await refresh_bat()

    # CarGurus is sync — run in thread to avoid blocking event loop
    loop = asyncio.get_event_loop()
    cg_saved = await loop.run_in_executor(None, refresh_cargurus)

    logger.info(
        "=== Refresh complete — BaT: +%d, CarGurus: +%d (%.0fs) ===",
        bat_saved, cg_saved, (datetime.utcnow() - start).total_seconds(),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = ArgumentParser(description="Refresh BaT and CarGurus listings")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    # Always run immediately on startup
    await run_refresh()

    if args.once:
        return

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_refresh, "interval", hours=12, id="refresh")
    scheduler.start()
    logger.info("Scheduler started — next run in 12 hours. Ctrl+C to stop.")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    asyncio.run(main())
