import asyncio
import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.normalizer import (
    infer_generation_from_year,
    normalize_body_style,
    normalize_generation,
    normalize_transmission,
    normalize_trim,
)
from app.schemas import ParsedListing

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "911DealRadar/1.0 (research; wei.zeng1993@gmail.com)"}


def _parse_title(title: str, url: str = "") -> dict:
    result = {}

    # Standard BaT format: "12,345-Mile 2019 Porsche 911 Carrera S Coupe"
    m = re.match(
        r"([\d,\.]+k?)-?[Mm]iles?\s+(\d{4})\s+Porsche\s+911\s+(.+)",
        title, re.IGNORECASE,
    )
    if m:
        mileage_raw = m.group(1).replace(",", "")
        year_raw, remainder = m.group(2), m.group(3)
        miles = float(mileage_raw.lower().replace("k", "")) * (1000 if "k" in mileage_raw.lower() else 1)
        result["mileage"] = int(miles)
        result["year"] = int(year_raw)
        result["body_style"] = normalize_body_style(remainder)
        result["trim"] = normalize_trim(remainder)
        return result

    # Fallback 1: no mileage prefix — "2025 Porsche 911 Turbo 50 Years"
    m = re.search(r"(\d{4})\s+Porsche\s+911\s+(.+)", title, re.IGNORECASE)
    if m:
        year_raw, remainder = m.group(1), m.group(2)
        result["year"] = int(year_raw)
        result["body_style"] = normalize_body_style(remainder)
        result["trim"] = normalize_trim(remainder)
        return result

    # Fallback 2: year from URL slug — /listing/2025-porsche-911-turbo-.../
    if url:
        m = re.search(r"/(\d{4})-porsche-911", url, re.IGNORECASE)
        if m:
            result["year"] = int(m.group(1))

    return result


def _parse_price(soup: BeautifulSoup) -> tuple[Optional[str], Optional[float]]:
    """Returns (price_type, price_value)."""
    # Combine text from both price containers — BaT uses either or both
    parts = []
    for cls in ("listing-stats", "listing-available-info"):
        el = soup.find(class_=cls)
        if el:
            parts.append(el.get_text(" ", strip=True))
    text = " ".join(parts)
    if not text:
        return None, None

    # "Sold for USD $313,000" or "Winning Bid USD $313,000" → sold
    sold_match = re.search(
        r"(?:Sold\s+for|Winning\s+Bid)[:\s]+USD\s*\$?([\d,]+)",
        text, re.IGNORECASE,
    )
    if sold_match:
        return "SOLD_PRICE", float(sold_match.group(1).replace(",", ""))

    # Active auction — current bid
    bid_match = re.search(r"Current\s+Bid[:\s]+USD\s*\$?([\d,]+)", text, re.IGNORECASE)
    if bid_match:
        return "BID_TO_PRICE", float(bid_match.group(1).replace(",", ""))

    return None, None


def _parse_description(text: str) -> dict:
    result = {}

    # Exact mileage
    m = re.search(r"([\d,]+)[\s-]mile", text, re.IGNORECASE)
    if m:
        result["mileage"] = int(m.group(1).replace(",", ""))

    # Generation (explicitly mentioned like "991.2" or "992.1")
    m = re.search(r"\b(99[12]\.[12])\b", text)
    if m:
        result["generation"] = m.group(1)

    # Transmission
    if re.search(r"\bPDK\b|dual-clutch", text, re.IGNORECASE):
        result["transmission"] = "PDK"
    elif re.search(r"\bmanual\b|six-speed|7-speed manual|MT\b", text, re.IGNORECASE):
        result["transmission"] = "MANUAL"

    # Drivetrain
    if re.search(r"all four wheels|all-wheel|AWD|4S|Carrera 4", text, re.IGNORECASE):
        result["drivetrain"] = "AWD"
    elif re.search(r"rear wheels|rear-wheel|RWD", text, re.IGNORECASE):
        result["drivetrain"] = "RWD"

    # Exterior color — usually first sentence "finished in X" or "X over"
    m = re.search(r"finished in ([A-Z][A-Za-z\s]+?)(?:\s+and|\s+over|\s+with|\.|,)", text)
    if m:
        result["exterior_color"] = m.group(1).strip()
    else:
        m = re.search(r"specified in ([A-Z][A-Za-z\s]+?) over", text)
        if m:
            result["exterior_color"] = m.group(1).strip()

    # Interior color — "X leather interior" or "over X leather"
    m = re.search(r"over (?:a )?([A-Z][A-Za-z\s]+?) (?:leather|interior)", text)
    if m:
        result["interior_color"] = m.group(1).strip()

    # Title/accident status
    if re.search(r"clean\s+title", text, re.IGNORECASE):
        result["title_status"] = "clean"
    if re.search(r"salvage|rebuilt\s+title", text, re.IGNORECASE):
        result["title_status"] = "salvage"
    if re.search(r"free of accidents|no accidents|no reported", text, re.IGNORECASE):
        result["accident_reported"] = False
    elif re.search(r"accident|damage reported", text, re.IGNORECASE):
        result["accident_reported"] = True

    # Owner count
    m = re.search(r"(\w+)-owner|(\w+)\s+owner", text, re.IGNORECASE)
    if m:
        word = (m.group(1) or m.group(2)).lower()
        words_to_int = {"one": 1, "two": 2, "three": 3, "single": 1, "1": 1, "2": 2, "3": 3}
        if word in words_to_int:
            result["owner_count"] = words_to_int[word]

    # CPO
    if re.search(r"\bCPO\b|certified pre-owned", text, re.IGNORECASE):
        result["cpo"] = True

    # Options — sentences mentioning equipment
    options = []
    for m in re.finditer(r"\b(sport chrono|sport exhaust|PASM|PDCC|PDLS|PCM|Bose|burmester|carbon ceramic|panoramic|sunroof|moonroof|lane change|adaptive cruise|sport seats|carbon fiber)\b", text, re.IGNORECASE):
        opt = m.group(1).title()
        if opt not in options:
            options.append(opt)
    result["options"] = options

    return result


def _parse_vin(soup: BeautifulSoup) -> Optional[str]:
    for strong in soup.find_all("strong"):
        if "Chassis" in strong.get_text():
            parent = strong.parent
            text = parent.get_text(" ", strip=True)
            m = re.search(r"Chassis[:\s]+([A-HJ-NPR-Z0-9]{17})", text, re.IGNORECASE)
            if m:
                return m.group(1)
    return None


def _parse_location(soup: BeautifulSoup) -> Optional[str]:
    for el in soup.find_all(string=re.compile(r"offered (from|by|in)", re.IGNORECASE)):
        m = re.search(r"offered (?:from|by|in) (?:a (?:dealer|seller) in )?([A-Z][A-Za-z\s,]+)", el, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


async def scrape(url: str) -> tuple[Optional[ParsedListing], Optional[int], Optional[str]]:
    """Returns (parsed_listing, http_status, restriction_signal).
    restriction_signal is set when the scrape was blocked or failed structurally.
    """
    await asyncio.sleep(1.5)
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=10, follow_redirects=True) as client:
            r = await client.get(url)
    except Exception as e:
        logger.error("BaT fetch failed for %s: %s", url, e)
        return None, None, "NETWORK_ERROR"

    if r.status_code == 403:
        logger.warning("BaT IP_BLOCK %s for %s", r.status_code, url)
        return None, r.status_code, "IP_BLOCK"
    if r.status_code == 429:
        logger.warning("BaT RATE_LIMIT %s for %s", r.status_code, url)
        return None, r.status_code, "RATE_LIMIT"
    if r.status_code == 503:
        logger.warning("BaT restriction %s for %s", r.status_code, url)
        return None, r.status_code, "IP_BLOCK"
    if r.status_code != 200:
        logger.error("BaT unexpected status %s for %s", r.status_code, url)
        return None, r.status_code, "STRUCTURAL_CHANGE"

    soup = BeautifulSoup(r.text, "lxml")

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""
    title_data = _parse_title(title, url=url)

    excerpt = soup.find(class_="post-excerpt")
    desc_text = excerpt.get_text(" ", strip=True) if excerpt else ""
    desc_data = _parse_description(desc_text)

    price_type, price_value = _parse_price(soup)
    vin = _parse_vin(soup)
    location = _parse_location(soup)

    year = title_data.get("year")
    generation = desc_data.pop("generation", None)
    if generation is None and year:
        generation = infer_generation_from_year(year)

    mileage = desc_data.get("mileage") or title_data.get("mileage")
    trim = title_data.get("trim")
    body_style = title_data.get("body_style")
    transmission = desc_data.get("transmission")

    asking_price = price_value if price_type == "BID_TO_PRICE" else None
    sold_price = price_value if price_type == "SOLD_PRICE" else None
    status = "SOLD" if price_type == "SOLD_PRICE" else "ACTIVE"
    final_price_type = price_type or "UNKNOWN_FINAL"

    required = ["year", "generation", "trim", "body_style", "transmission", "mileage", "asking_price"]
    values = {
        "year": year, "generation": generation, "trim": trim,
        "body_style": body_style, "transmission": transmission,
        "mileage": mileage, "asking_price": asking_price or sold_price,
    }
    filled = sum(1 for v in values.values() if v is not None)

    parsed = ParsedListing(
        year=year,
        generation=generation,
        trim=trim,
        body_style=body_style,
        transmission=transmission,
        drivetrain=desc_data.get("drivetrain"),
        mileage=mileage,
        asking_price=asking_price,
        sold_price=sold_price,
        exterior_color=desc_data.get("exterior_color"),
        interior_color=desc_data.get("interior_color"),
        location=location,
        seller_type="AUCTION",
        vin=vin,
        options=desc_data.get("options", []),
        modifications=[],
        risk_signals=[],
        title_status=desc_data.get("title_status"),
        accident_reported=desc_data.get("accident_reported"),
        owner_count=desc_data.get("owner_count"),
        cpo=desc_data.get("cpo"),
        parser_confidence=round(filled / len(required), 2),
        missing_fields=[k for k, v in values.items() if v is None],
    )
    return parsed, r.status_code, None
