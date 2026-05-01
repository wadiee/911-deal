"""
Batch ingest BaT Porsche 911 listings (sold and active).

Usage:
    # Discover and ingest from N pages of BaT's 911 results
    uv run python scripts/ingest_bat.py --pages 10

    # Ingest from a URL file (one URL per line)
    uv run python scripts/ingest_bat.py --file bat_urls.txt

    # Ingest from stdin
    cat bat_urls.txt | uv run python scripts/ingest_bat.py
"""

import asyncio
import logging
import sys
import uuid
from argparse import ArgumentParser
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import httpx
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine
from app.models import Listing, ScrapeEvent
from app.scrapers.bat import scrape as bat_scrape

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "911DealRadar/1.0 (research; wei.zeng1993@gmail.com)"}

# JSON API — returns structured data with sold prices, titles, URLs, and pagination info
BAT_API_URL = (
    "https://bringatrailer.com/wp-json/bringatrailer/1.0/data/listings-filter"
    "?page={page}&per_page=36&get_items=1&get_stats=0&sort=td"
    "&location%5B%5D=US&include_s=911&state=sold"
)

# All generations stored — comp_matcher penalizes cross-generation matches at runtime.
# This means we never need to re-scrape when we expand beyond 991.2.


async def discover_urls(pages: int) -> list[str]:
    """Call BaT's listings-filter API to collect sold Porsche 911 listing URLs.

    Each API page returns 36 items with title, url, and sold price.
    Non-911 results are filtered out by title before any individual listing is fetched.
    Stops automatically when pages_total is reached.
    """
    found: list[str] = []
    async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
        for page in range(1, pages + 1):
            api_url = BAT_API_URL.format(page=page)
            logger.info("API page %d: %s", page, api_url)
            try:
                r = await client.get(api_url)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.error("API fetch failed on page %d: %s", page, e)
                break

            pages_total = data.get("pages_total", 0)
            items = data.get("items", [])

            p911_urls = [
                item["url"]
                for item in items
                if "porsche 911" in item.get("title", "").lower() and item.get("url")
            ]

            logger.info(
                "  Page %d/%d: %d Porsche 911 URLs (of %d items)",
                page, pages_total, len(p911_urls), len(items),
            )
            found.extend(p911_urls)

            if page >= pages_total:
                logger.info("Reached last API page (%d)", pages_total)
                break

            await asyncio.sleep(1)

    return list(dict.fromkeys(found))


def _load_existing(session: Session) -> tuple[set[str], set[str]]:
    vins = set(session.exec(select(Listing.vin).where(Listing.vin.isnot(None))).all())
    urls = set(session.exec(select(Listing.source_url).where(Listing.source_url.isnot(None))).all())
    return vins, urls


async def ingest(urls: list[str]) -> None:
    saved = 0
    skipped_dup = 0
    skipped_no_price = 0
    failed_scrape = 0
    failed_parse = 0
    run_id = str(uuid.uuid4())

    with Session(engine) as session:
        existing_vins, existing_urls = _load_existing(session)
    logger.info("Loaded %d existing VINs, %d existing URLs from DB", len(existing_vins), len(existing_urls))

    for i, url in enumerate(urls, 1):
        logger.info("[%d/%d] %s", i, len(urls), url)

        if url in existing_urls:
            logger.info("  Skip: URL already in DB")
            skipped_dup += 1
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

        if parsed is None:
            logger.warning("  Failed to scrape (blocked or network error)")
            failed_scrape += 1
            continue

        # Must have a year to tag the generation correctly
        if not parsed.year:
            logger.info("  Skip: year could not be parsed")
            failed_parse += 1
            continue

        # Must have a price to be useful as a comp
        if not parsed.sold_price and not parsed.asking_price:
            logger.info("  Skip: no price extracted")
            skipped_no_price += 1
            continue

        # Must have at minimum year + trim
        if not parsed.trim:
            logger.info("  Skip: missing trim (confidence %.2f, missing=%s)",
                        parsed.parser_confidence, parsed.missing_fields)
            failed_parse += 1
            continue

        # VIN dedup
        if parsed.vin and parsed.vin in existing_vins:
            logger.info("  Skip: VIN %s already in DB", parsed.vin)
            skipped_dup += 1
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
            session.refresh(listing)

        if parsed.vin:
            existing_vins.add(parsed.vin)
        existing_urls.add(url)
        saved += 1

        price_str = (
            f"sold ${parsed.sold_price:,.0f}" if parsed.sold_price
            else f"bid ${parsed.asking_price:,.0f}"
        )
        logger.info(
            "  Saved: %s %s %s | %s | %s | conf %.2f",
            parsed.year, parsed.trim, parsed.body_style or "",
            parsed.transmission or "?",
            price_str,
            parsed.parser_confidence,
        )

    print(
        f"\nDone.\n"
        f"  Saved:              {saved}\n"
        f"  Skipped (dup):      {skipped_dup}\n"
        f"  Skipped (no price): {skipped_no_price}\n"
        f"  Failed (scrape):    {failed_scrape}\n"
        f"  Failed (parse):     {failed_parse}"
    )

    # Summary by generation and trim
    with Session(engine) as session:
        bat_rows = session.exec(select(Listing).where(Listing.source == "bringatrailer")).all()
        sold = [r for r in bat_rows if r.price_type == "SOLD_PRICE"]
        print(f"\nDB BaT total: {len(bat_rows)} | Sold comps: {len(sold)}")

        by_gen: dict[str, int] = {}
        for r in bat_rows:
            k = r.generation or "UNKNOWN"
            by_gen[k] = by_gen.get(k, 0) + 1
        print("\nBy generation:")
        for gen, count in sorted(by_gen.items(), key=lambda x: -x[1]):
            print(f"  {gen:<10} {count}")

        by_trim: dict[str, int] = {}
        for r in bat_rows:
            k = r.trim or "UNKNOWN"
            by_trim[k] = by_trim.get(k, 0) + 1
        print("\nBy trim:")
        for trim, count in sorted(by_trim.items(), key=lambda x: -x[1]):
            print(f"  {trim:<20} {count}")


async def main() -> None:
    parser = ArgumentParser(description="Ingest BaT Porsche 911 listings into the DB")
    parser.add_argument(
        "--pages", type=int, default=0,
        help="Number of BaT 911 category pages to discover URLs from (2 pages ≈ 30–40 listings)",
    )
    parser.add_argument(
        "--file", type=str, default=None,
        help="Text file with one BaT listing URL per line",
    )
    args = parser.parse_args()

    urls: list[str] = []

    if args.pages > 0:
        logger.info("Discovering URLs from %d BaT results page(s)...", args.pages)
        urls = await discover_urls(args.pages)
        logger.info("Discovered %d unique listing URLs", len(urls))
    elif args.file:
        with open(args.file) as f:
            urls = [line.strip() for line in f if line.strip().startswith("http")]
        logger.info("Loaded %d URLs from %s", len(urls), args.file)
    elif not sys.stdin.isatty():
        urls = [line.strip() for line in sys.stdin if line.strip().startswith("http")]
        logger.info("Loaded %d URLs from stdin", len(urls))
    else:
        parser.print_help()
        sys.exit(1)

    if not urls:
        print("No valid URLs found to process.")
        sys.exit(1)

    await ingest(urls)


if __name__ == "__main__":
    asyncio.run(main())
