from decimal import Decimal
from uuid import UUID
from typing import Optional

import re

import httpx
from bs4 import BeautifulSoup
import markdown as md_lib
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlmodel import Session

from app import comp_matcher, report_generator
from app.database import get_session
from app.models import Listing, Report, CompMatch, EmailCapture
from app.scrapers import registry
from app.valuation_service import ValuationInput, compute

_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


_BOT_SIGNALS = [
    "enable javascript", "enable js", "please enable",
    "captcha", "cf-challenge", "access denied",
    "unusual traffic", "not a robot", "verify you are human",
    "datadome", "distil-referrer",
]


async def _fetch_url_text(url: str) -> tuple[Optional[str], bool]:
    """Fetch a URL and return (visible_text, bot_protected).
    bot_protected=True means the page returned a CAPTCHA or bot-block page.
    """
    try:
        async with httpx.AsyncClient(headers=_FETCH_HEADERS, timeout=15, follow_redirects=True) as client:
            r = await client.get(url)
        if r.status_code != 200:
            return None, False
        raw_lower = r.text.lower()
        if any(signal in raw_lower for signal in _BOT_SIGNALS):
            return None, True
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:12000], False
    except Exception:
        return None, False

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["zip"] = zip
templates.env.filters["markdown"] = lambda text: Markup(md_lib.markdown(text or "", extensions=["nl2br"]))


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/submit", response_class=HTMLResponse)
def submit_get(request: Request):
    return templates.TemplateResponse(request, "submit.html", {})


@router.post("/submit", response_class=HTMLResponse)
async def submit_post(
    request: Request,
    source_url: Optional[str] = Form(default=None),
    raw_text: Optional[str] = Form(default=None),
    price_override: Optional[float] = Form(default=None),
    mileage_override: Optional[int] = Form(default=None),
    notes: Optional[str] = Form(default=None),
    session: Session = Depends(get_session),
):
    url = source_url.strip() if source_url and source_url.strip() else None
    text = raw_text.strip() if raw_text and raw_text.strip() else None

    # 1. Try dedicated scraper first if URL provided
    parsed = None
    if url:
        parsed = await registry.scrape(url)

    # 2. Fall through to AI parser — use pasted text, or fetch the URL if no text given
    if parsed is None:
        from app import listing_parser
        if not text and url:
            fetched, bot_protected = await _fetch_url_text(url)
            if bot_protected:
                return templates.TemplateResponse(request, "submit.html", {
                    "error": "That site blocks automated access (Carfax, CarMax, AutoTrader, etc.). Please copy and paste the listing text below instead.",
                    "source_url": url or "",
                    "raw_text": "",
                })
            if not fetched:
                return templates.TemplateResponse(request, "submit.html", {
                    "error": "Could not load that URL. Please paste the listing text instead.",
                    "source_url": url or "",
                    "raw_text": "",
                })
            text = fetched
        if not text:
            return templates.TemplateResponse(request, "submit.html", {
                "error": "Please provide a listing URL or paste the listing text.",
                "source_url": "",
                "raw_text": "",
            })
        parsed = await listing_parser.parse(text)

    # 3. Validate this looks like a Porsche 911
    if parsed.year is None and parsed.trim is None and parsed.generation is None:
        return templates.TemplateResponse(request, "submit.html", {
            "error": "This doesn't look like a Porsche 911 listing. Please check the URL or paste the listing text.",
            "source_url": url or "",
            "raw_text": text or "",
        })

    # 4. Apply user overrides
    if price_override is not None:
        parsed.asking_price = Decimal(str(price_override))
    if mileage_override is not None:
        parsed.mileage = mileage_override

    # 5. Determine source label
    if url:
        if "bringatrailer.com" in url:
            source = "bringatrailer"
        elif "carsandbids.com" in url:
            source = "carsandbids"
        elif "cargurus.com" in url:
            source = "cargurus"
        else:
            source = "user_submitted"
    else:
        source = "user_submitted"

    price_type = "SOLD_PRICE" if parsed.sold_price else "ASKING_PRICE"
    status = "SOLD" if parsed.sold_price else "ACTIVE"

    # 6. Save listing
    listing = Listing(
        source=source,
        source_url=url,
        status=status,
        price_type=price_type,
        asking_price=parsed.asking_price,
        sold_price=parsed.sold_price,
        year=parsed.year,
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
        raw_text=text,
        normalized_notes=notes,
    )
    session.add(listing)
    session.commit()
    session.refresh(listing)

    # 7. Generate report inline
    comp_scores = comp_matcher.find_comps(listing, session, limit=20)
    comp_listings_map = {
        str(cs.listing_id): session.get(Listing, cs.listing_id)
        for cs in comp_scores
    }
    valuation = compute(ValuationInput(listing, comp_scores, comp_listings_map))
    top_comps = [
        (comp_scores[i], comp_listings_map[str(comp_scores[i].listing_id)])
        for i in range(min(5, len(comp_scores)))
        if comp_listings_map.get(str(comp_scores[i].listing_id))
    ]
    report_out = report_generator.generate(
        report_generator.ReportInput(listing, valuation, top_comps)
    )

    report = Report(
        target_listing_id=listing.id,
        verdict=report_out.verdict,
        confidence_level=valuation.confidence_level,
        asking_price=listing.asking_price or listing.sold_price,
        estimated_low=valuation.estimated_market_low,
        estimated_high=valuation.estimated_market_high,
        recommended_offer_low=valuation.recommended_offer_low,
        recommended_offer_high=valuation.recommended_offer_high,
        sold_comp_summary={
            "count": valuation.sold_comp_count,
            "low": str(valuation.sold_comp_low),
            "high": str(valuation.sold_comp_high),
        },
        active_comp_summary={
            "count": valuation.active_asking_count,
            "low": str(valuation.active_asking_low),
            "high": str(valuation.active_asking_high),
        },
        risk_flags={"flags": report_out.risk_flags},
        desirability_factors={"factors": report_out.desirability_factors},
        seller_questions={"questions": report_out.seller_questions},
        report_markdown=report_out.report_markdown,
    )
    session.add(report)
    session.flush()  # ensure report row exists before FK refs in comp_matches

    for cs in comp_scores[:10]:
        session.add(CompMatch(
            report_id=report.id,
            comp_listing_id=cs.listing_id,
            similarity_score=Decimal(str(cs.similarity_score)),
            data_weight=Decimal(str(cs.data_weight)),
            final_weight=Decimal(str(cs.final_weight)),
            match_reason={"bonuses": cs.match_reasons, "penalties": cs.penalty_reasons},
        ))

    session.commit()
    session.refresh(report)

    return RedirectResponse(url=f"/reports/{report.id}", status_code=303)


@router.get("/reports/{report_id}", response_class=HTMLResponse)
def view_report(report_id: str, request: Request, session: Session = Depends(get_session)):
    report = session.get(Report, UUID(report_id))
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    target = session.get(Listing, report.target_listing_id)

    comp_matches = session.exec(
        __import__("sqlmodel", fromlist=["select"]).select(CompMatch)
        .where(CompMatch.report_id == report.id)
        .order_by(CompMatch.final_weight.desc())
    ).all()

    comp_listings = [
        session.get(Listing, cm.comp_listing_id)
        for cm in comp_matches
    ]

    return templates.TemplateResponse(request, "report.html", {
        "report": report,
        "target": target,
        "comp_matches": comp_matches,
        "comp_listings": comp_listings,
    })


@router.post("/email-capture", response_class=HTMLResponse)
def email_capture(
    request: Request,
    email: str = Form(),
    report_id: str = Form(default=""),
    name: Optional[str] = Form(default=None),
    trim_interest: Optional[str] = Form(default=None),
    budget_min: Optional[int] = Form(default=None),
    budget_max: Optional[int] = Form(default=None),
    session: Session = Depends(get_session),
):
    email = email.strip().lower()
    if not email or "@" not in email:
        return HTMLResponse('<p class="text-red-500 text-sm">Please enter a valid email address.</p>')

    capture = EmailCapture(
        email=email,
        report_id=UUID(report_id) if report_id else None,
        name=name.strip() if name and name.strip() else None,
        trim_interest=trim_interest.strip() if trim_interest and trim_interest.strip() else None,
        budget_min=budget_min,
        budget_max=budget_max,
    )
    session.add(capture)
    session.commit()

    return HTMLResponse('<p class="text-green-600 text-sm font-medium">You\'re on the list. We\'ll notify you when new matches appear.</p>')
