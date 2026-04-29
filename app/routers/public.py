from decimal import Decimal
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app import comp_matcher, report_generator
from app.database import get_session
from app.models import Listing, Report, CompMatch, EmailCapture
from app.scrapers import registry
from app.valuation_service import ValuationInput, compute

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["zip"] = zip


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

    # 1. Try scraper first if URL provided
    parsed = None
    if url:
        parsed = await registry.scrape(url)

    # 2. Fall through to AI parser with raw text
    if parsed is None:
        if not text:
            return templates.TemplateResponse(request, "submit.html", {
                "error": "Please provide a listing URL or paste the listing text.",
                "source_url": url or "",
                "raw_text": text or "",
            })
        from app import listing_parser
        parsed = await listing_parser.parse(text)

    # 3. Apply user overrides
    if price_override is not None:
        parsed.asking_price = Decimal(str(price_override))
    if mileage_override is not None:
        parsed.mileage = mileage_override

    # 4. Determine source label
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

    # 5. Save listing
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

    # 6. Generate report inline
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
        asking_price=listing.asking_price,
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
    session: Session = Depends(get_session),
):
    email = email.strip().lower()
    if not email or "@" not in email:
        return HTMLResponse('<p class="text-red-500 text-sm">Please enter a valid email address.</p>')

    capture = EmailCapture(
        email=email,
        report_id=UUID(report_id) if report_id else None,
    )
    session.add(capture)
    session.commit()

    return HTMLResponse('<p class="text-green-600 text-sm font-medium">You\'re on the list. We\'ll notify you when new matches appear.</p>')
