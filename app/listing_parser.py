import json
import logging
import re
from typing import Optional

import anthropic
from fastapi import HTTPException

from app.config import settings
from app.normalizer import (
    normalize_body_style,
    normalize_generation,
    normalize_seller_type,
    normalize_transmission,
    normalize_trim,
    infer_generation_from_year,
)
from app.schemas import ParsedListing

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ["year", "generation", "trim", "body_style", "transmission", "mileage", "asking_price"]

SYSTEM_PROMPT = """You are a Porsche 911 listing data extractor. Your job is to extract structured fields from raw listing text.

Rules:
- Extract ONLY what is explicitly stated in the text. Do not infer or guess values not present.
- Return a JSON object with exactly these fields:
  - year (integer or null)
  - generation (string like "991.2", "992.1", or null)
  - trim (string like "Carrera S", "GTS", or null)
  - body_style (string like "coupe", "cabriolet", "targa", or null)
  - transmission (string like "PDK", "manual", "automatic", or null)
  - drivetrain (string like "RWD", "AWD", or null)
  - mileage (integer or null)
  - asking_price (number or null)
  - sold_price (number or null)
  - exterior_color (string or null)
  - interior_color (string or null)
  - location (string or null)
  - seller_type (string like "dealer", "private", "auction", "cpo", or null)
  - vin (string or null)
  - options (array of strings, empty array if none)
  - modifications (array of strings, empty array if none)
  - risk_signals (array of strings describing anything suspicious, empty array if none)
  - title_status (string like "clean", "salvage", "rebuilt", or null)
  - accident_reported (boolean or null)
  - owner_count (integer or null)
  - cpo (boolean or null)
- Return ONLY valid JSON with no markdown, no explanation, no extra text."""


def _clean_text(raw: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw)
    text = re.sub(r" {3,}", "  ", text)
    return text.strip()


def _extract_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    return json.loads(content)


async def parse(raw_text: str) -> ParsedListing:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    cleaned = _clean_text(raw_text)

    try:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": cleaned}],
        )
        raw_json = _extract_json(response.content[0].text)
    except json.JSONDecodeError as e:
        logger.error("Parser returned unparseable JSON: %s", e)
        raise HTTPException(status_code=502, detail="Parser error: invalid JSON response")
    except Exception as e:
        logger.error("Parser LLM call failed: %s", e)
        raise HTTPException(status_code=502, detail="Parser error")

    generation = normalize_generation(raw_json.get("generation") or "") or None
    trim = normalize_trim(raw_json.get("trim") or "") or None
    transmission = normalize_transmission(raw_json.get("transmission") or "") or None
    body_style = normalize_body_style(raw_json.get("body_style") or "") or None
    seller_type = normalize_seller_type(raw_json.get("seller_type") or "") or None

    year = raw_json.get("year")
    if generation is None and year:
        generation = infer_generation_from_year(int(year), trim)

    result = ParsedListing(
        year=year,
        generation=generation,
        trim=trim,
        body_style=body_style,
        transmission=transmission,
        drivetrain=raw_json.get("drivetrain"),
        mileage=raw_json.get("mileage"),
        asking_price=raw_json.get("asking_price"),
        sold_price=raw_json.get("sold_price"),
        exterior_color=raw_json.get("exterior_color"),
        interior_color=raw_json.get("interior_color"),
        location=raw_json.get("location"),
        seller_type=seller_type,
        vin=raw_json.get("vin"),
        options=raw_json.get("options") or [],
        modifications=raw_json.get("modifications") or [],
        risk_signals=raw_json.get("risk_signals") or [],
        title_status=raw_json.get("title_status"),
        accident_reported=raw_json.get("accident_reported"),
        owner_count=raw_json.get("owner_count"),
        cpo=raw_json.get("cpo"),
    )

    filled = sum(1 for f in REQUIRED_FIELDS if getattr(result, f) is not None)
    result.parser_confidence = round(filled / len(REQUIRED_FIELDS), 2)
    result.missing_fields = [f for f in REQUIRED_FIELDS if getattr(result, f) is None]

    return result
