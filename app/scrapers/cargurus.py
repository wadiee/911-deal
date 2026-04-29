import asyncio
import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.normalizer import infer_generation_from_year, normalize_body_style, normalize_trim
from app.schemas import ParsedListing

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# Porsche 911 search URL — entityId=d404 is the 911, m48 is Porsche
SEARCH_URL = "https://www.cargurus.com/search?zip={zip}&carType=USED&entityId=d404&makeModelTrimPaths=m48%2Cm48%2Fd404"


def _parse_trim_string(trim_str: str) -> dict:
    """
    CarGurus trim strings look like: 'Carrera 4S Coupe AWD', 'GT3 Coupe RWD'
    Parse out canonical trim, body style, and drivetrain.
    """
    result = {}
    result["trim"] = normalize_trim(trim_str)
    result["body_style"] = normalize_body_style(trim_str)

    if "AWD" in trim_str or "4WD" in trim_str:
        result["drivetrain"] = "AWD"
    elif "RWD" in trim_str:
        result["drivetrain"] = "RWD"

    return result


def _extract_listings(html: str) -> list[dict]:
    import json

    match = re.search(
        r'__remixContext\.r\("routes/[^"]+",\s*"recommendations",\s*(\[.+?\])\)',
        html,
        re.DOTALL,
    )
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as e:
            logger.error("CarGurus JSON parse error: %s", e)
    return []


def _listing_to_parsed(raw: dict) -> Optional[ParsedListing]:
    year = raw.get("year")
    trim_str = raw.get("trim", "")
    trim_data = _parse_trim_string(trim_str)

    generation = infer_generation_from_year(year) if year else None

    required = ["year", "generation", "trim", "body_style", "transmission", "mileage", "asking_price"]
    values = {
        "year": year,
        "generation": generation,
        "trim": trim_data.get("trim"),
        "body_style": trim_data.get("body_style"),
        "transmission": None,  # not in search results
        "mileage": raw.get("mileage"),
        "asking_price": raw.get("price"),
    }
    filled = sum(1 for v in values.values() if v is not None)

    seller_type_raw = raw.get("sellerType", "")
    if seller_type_raw == "DEALER":
        seller_type = "DEALER"
    elif seller_type_raw == "PRIVATE":
        seller_type = "PRIVATE"
    else:
        seller_type = None

    return ParsedListing(
        year=year,
        generation=generation,
        trim=trim_data.get("trim"),
        body_style=trim_data.get("body_style"),
        drivetrain=trim_data.get("drivetrain"),
        mileage=raw.get("mileage"),
        asking_price=raw.get("price"),
        exterior_color=raw.get("exteriorColor"),
        location=raw.get("cityRegion"),
        seller_type=seller_type,
        vin=raw.get("vin"),
        options=[],
        modifications=[],
        risk_signals=[],
        parser_confidence=round(filled / len(required), 2),
        missing_fields=[k for k, v in values.items() if v is None],
    )


async def scrape_search(zip_code: str = "10001") -> list[ParsedListing]:
    """Scrape the CarGurus 911 search results page for a given zip code."""
    url = SEARCH_URL.format(zip=zip_code)
    await asyncio.sleep(1.5)

    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            r = await client.get(url)
    except Exception as e:
        logger.error("CarGurus fetch failed for zip=%s: %s", zip_code, e)
        return []

    if r.status_code in (403, 429, 503):
        logger.warning("CarGurus restriction %s for zip=%s", r.status_code, zip_code)
        return []
    if r.status_code != 200:
        logger.error("CarGurus unexpected status %s for zip=%s", r.status_code, zip_code)
        return []

    raw_listings = _extract_listings(r.text)
    if not raw_listings:
        logger.warning("CarGurus: no listings extracted for zip=%s", zip_code)
        return []

    results = []
    for raw in raw_listings:
        parsed = _listing_to_parsed(raw)
        if parsed:
            results.append(parsed)

    logger.info("CarGurus: extracted %d listings for zip=%s", len(results), zip_code)
    return results


async def scrape(url: str) -> Optional[ParsedListing]:
    """Scrape a single CarGurus listing URL — extracts from the page's remixContext."""
    await asyncio.sleep(1.5)
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            r = await client.get(url)
    except Exception as e:
        logger.error("CarGurus listing fetch failed for %s: %s", url, e)
        return None

    if r.status_code != 200:
        logger.warning("CarGurus listing status %s for %s", r.status_code, url)
        return None

    # Individual listing pages embed a single listing in the remixContext
    import json
    match = re.search(r'"listing"\s*:\s*(\{[^}]{200,}\})', r.text, re.DOTALL)
    if not match:
        # Fall back to search-style recommendations extraction
        listings = _extract_listings(r.text)
        if listings:
            return _listing_to_parsed(listings[0])
        return None

    try:
        raw = json.loads(match.group(1))
        return _listing_to_parsed(raw)
    except Exception as e:
        logger.error("CarGurus listing parse error: %s", e)
        return None
