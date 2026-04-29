import asyncio
import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.normalizer import infer_generation_from_year, normalize_body_style, normalize_trim
from app.schemas import ParsedListing

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "911DealRadar/1.0 (research; wei.zeng1993@gmail.com)"}


def _parse_og_title(title: str) -> dict:
    """
    CnB OG title format: "2020 Porsche 911 Carrera 4S Coupe - tagline"
    """
    result = {}
    m = re.match(r"(\d{4})\s+Porsche\s+911\s+(.+?)(?:\s+-\s+.+)?$", title)
    if not m:
        return result

    result["year"] = int(m.group(1))
    remainder = m.group(2)

    result["body_style"] = normalize_body_style(remainder)
    result["trim"] = normalize_trim(remainder)

    # drivetrain from tagline ("AWD" appears in tagline after the dash)
    if "AWD" in title:
        result["drivetrain"] = "AWD"
    elif "RWD" in title:
        result["drivetrain"] = "RWD"

    return result


def _parse_tagline(tagline: str) -> dict:
    """Extract features from the CnB subtitle after the dash."""
    result = {}

    if re.search(r"\bPDK\b|dual-clutch", tagline, re.IGNORECASE):
        result["transmission"] = "PDK"
    elif re.search(r"\bmanual\b|6-speed|7-speed", tagline, re.IGNORECASE):
        result["transmission"] = "MANUAL"

    options = []
    for m in re.finditer(r"\b(Sport Chrono|Sport Exhaust|PASM|PDCC|PDLS|Bose|Burmester|Carbon Ceramic|Panoramic|Lane Change|Adaptive Cruise)\b", tagline, re.IGNORECASE):
        options.append(m.group(1).title())
    if "Unmodified" in tagline:
        result["modifications"] = []
    result["options"] = options

    return result


async def scrape(url: str) -> Optional[ParsedListing]:
    await asyncio.sleep(1.5)
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=10, follow_redirects=True) as client:
            r = await client.get(url)
    except Exception as e:
        logger.error("CnB fetch failed for %s: %s", url, e)
        return None

    if r.status_code in (403, 429, 503):
        logger.warning("CnB restriction %s for %s", r.status_code, url)
        return None
    if r.status_code != 200:
        logger.error("CnB unexpected status %s for %s", r.status_code, url)
        return None

    soup = BeautifulSoup(r.text, "lxml")

    og_title_tag = soup.find("meta", property="og:title")
    og_title = og_title_tag.get("content", "") if og_title_tag else ""

    title_data = _parse_og_title(og_title)
    tagline_data = {}
    if " - " in og_title:
        tagline = og_title.split(" - ", 1)[1]
        tagline_data = _parse_tagline(tagline)

    year = title_data.get("year")
    generation = infer_generation_from_year(year) if year else None

    required = ["year", "generation", "trim", "body_style", "transmission", "mileage", "asking_price"]
    values = {
        "year": year,
        "generation": generation,
        "trim": title_data.get("trim"),
        "body_style": title_data.get("body_style"),
        "transmission": tagline_data.get("transmission"),
        "mileage": None,
        "asking_price": None,
    }
    filled = sum(1 for v in values.values() if v is not None)

    return ParsedListing(
        year=year,
        generation=generation,
        trim=title_data.get("trim"),
        body_style=title_data.get("body_style"),
        transmission=tagline_data.get("transmission"),
        drivetrain=title_data.get("drivetrain"),
        options=tagline_data.get("options", []),
        modifications=tagline_data.get("modifications", []),
        risk_signals=[],
        seller_type="AUCTION",
        parser_confidence=round(filled / len(required), 2),
        missing_fields=[k for k, v in values.items() if v is None],
    )
