"""
Ingest 2017-2019 Porsche 911 listings from CarGurus across target metros.
Uses local distance per metro (100mi radius) so each city surfaces distinct inventory.
Deduplicates by VIN before saving to DB.

Usage:
    uv run python scripts/ingest_cargurus.py
"""
import json
import logging
import re
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select
from app.database import engine
from app.models import Listing, PriceObservation
from app.normalizer import infer_generation_from_year, normalize_body_style, normalize_trim

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# Local distance search per metro — surfaces genuinely local inventory
BASE_URL = (
    "https://www.cargurus.com/search"
    "?sourceContext=carGurusHomePageModel"
    "&makeModelTrimPaths=m48%2Cm48%2Fd404"
    "&isDeliveryEnabled=true"
    "&priceDropsOnly=false"
    "&distance=100"
    "&sortDirection=ASC"
    "&sortType=BEST_MATCH"
    "&startYear=2017"
    "&endYear=2019"
    "&vehicleHistoryOptions=CLEAN_TITLE%2CUNDAMAGED_FRAME%2CNO_THEFT_HISTORY%2CLEMON_FREE%2CNON_SALVAGE"
    "&zip={zip}"
    "&startIndex={start}"
)

# Target metros — multiple zip codes per metro for fuller coverage
METRO_ZIPS = {
    "SF Bay Area":    ["94102", "94601", "95112"],  # SF, Oakland, San Jose
    "Los Angeles":    ["90001", "90210", "91101"],  # LA, Beverly Hills, Pasadena
    "New Jersey":     ["07101", "07601", "08901"],  # Newark, Hackensack, New Brunswick
    "Dallas":         ["75201", "75039", "75063"],  # Dallas, Irving, Las Colinas
    "Houston":        ["77001", "77057", "77077"],  # Houston downtown, Galleria, West Houston
    "Seattle":        ["98101", "98033", "98004"],  # Seattle, Kirkland, Bellevue
    "Portland":       ["97201", "97202", "97223"],  # Portland, Sellwood, Tigard
    "Salt Lake City": ["84101", "84102", "84121"],  # SLC, Capitol Hill, Cottonwood Heights
    "Phoenix":        ["85001", "85251", "85254"],  # Phoenix, Scottsdale, North Scottsdale
    "Tucson":         ["85701", "85718", "85750"],  # Tucson downtown, Foothills, East Tucson
}


def extract_listings(html: str) -> list[dict]:
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


MIN_PRICE = 50_000
MAX_PRICE = 600_000
VALID_YEARS = range(2017, 2020)  # 991.2 only


def raw_to_listing(raw: dict) -> Optional[Listing]:
    year = raw.get("year")
    if not year or year not in VALID_YEARS:
        return None

    price = raw.get("price")
    if not price or not (MIN_PRICE <= price <= MAX_PRICE):
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


def run():
    # Load VINs already in DB to skip on restart
    with Session(engine) as session:
        existing = session.exec(select(Listing.vin).where(Listing.vin.is_not(None))).all()
        seen_vins: set = set(existing)
    logger.info("Pre-loaded %d existing VINs from DB", len(seen_vins))

    total_saved = 0
    total_skipped = 0

    with httpx.Client(headers=HEADERS) as client:
        for metro, zips in METRO_ZIPS.items():
            logger.info("=== %s ===", metro)
            metro_saved = 0

            for zip_code in zips:
                for start in [0, 20, 40]:
                    try:
                        url = BASE_URL.format(zip=zip_code, start=start)
                        r = client.get(url, timeout=20, follow_redirects=True)
                    except Exception as e:
                        logger.error("Fetch error zip=%s start=%d: %s", zip_code, start, e)
                        time.sleep(3)
                        continue

                    if r.status_code != 200:
                        logger.warning("Status %d for zip=%s start=%d", r.status_code, zip_code, start)
                        break

                    raw_listings = extract_listings(r.text)
                    if not raw_listings:
                        logger.info("  zip=%s start=%d: no listings (end of results)", zip_code, start)
                        break

                    new_this_page = 0
                    with Session(engine) as session:
                        for raw in raw_listings:
                            vin = raw.get("vin")
                            if vin and vin in seen_vins:
                                total_skipped += 1
                                continue

                            listing = raw_to_listing(raw)
                            if listing is None:
                                continue

                            session.add(listing)
                            session.flush()
                            session.add(PriceObservation(
                                listing_id=listing.id,
                                observed_at=datetime.utcnow(),
                                observed_price=listing.asking_price,
                                observation_type="INITIAL_ASK",
                                source_url=listing.source_url,
                            ))

                            if vin:
                                seen_vins.add(vin)
                            total_saved += 1
                            metro_saved += 1
                            new_this_page += 1

                        session.commit()

                    logger.info("  zip=%s start=%d: %d on page, %d new", zip_code, start, len(raw_listings), new_this_page)
                    time.sleep(2)

            logger.info("  %s: +%d listings saved", metro, metro_saved)

    logger.info("Done. Total saved: %d | Skipped (dup VIN): %d", total_saved, total_skipped)

    # Print summary
    with Session(engine) as session:
        all_listings = session.exec(select(Listing).where(Listing.source == "cargurus")).all()
        by_trim = {}
        for l in all_listings:
            k = l.trim or "UNKNOWN"
            by_trim[k] = by_trim.get(k, 0) + 1
        logger.info("DB total cargurus listings: %d", len(all_listings))
        for trim, count in sorted(by_trim.items(), key=lambda x: -x[1]):
            logger.info("  %-20s %d", trim, count)


if __name__ == "__main__":
    run()
