from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app import comp_matcher, report_generator
from app.database import get_session
from app.models import Listing, Report, CompMatch
from app.schemas import ParsedListing, ParseListingRequest
from app.scrapers import registry
from app.valuation_service import ValuationInput, compute

router = APIRouter()


@router.get("/status")
def api_status():
    return {"status": "ok"}


@router.post("/listings/parse", response_model=ParsedListing)
async def parse_listing(body: ParseListingRequest):
    if body.source_url:
        result = await registry.scrape(body.source_url)
        if result is not None:
            return result
        if not body.raw_text:
            raise HTTPException(status_code=422, detail="No scraper available for this URL and no raw_text provided")

    if not body.raw_text:
        raise HTTPException(status_code=422, detail="Provide source_url or raw_text")

    from app import listing_parser
    return await listing_parser.parse(body.raw_text)


@router.get("/comps")
def get_comps(listing_id: str, session: Session = Depends(get_session)):
    target = session.get(Listing, UUID(listing_id))
    if not target:
        raise HTTPException(status_code=404, detail="Listing not found")

    scores = comp_matcher.find_comps(target, session)

    return {
        "target_listing_id": listing_id,
        "target": {
            "year": target.year,
            "generation": target.generation,
            "trim": target.trim,
            "body_style": target.body_style,
            "transmission": target.transmission,
            "mileage": target.mileage,
            "asking_price": str(target.asking_price) if target.asking_price else None,
            "location": target.location,
        },
        "comps": [
            {
                "listing_id": str(s.listing_id),
                "similarity_score": s.similarity_score,
                "data_weight": s.data_weight,
                "final_weight": s.final_weight,
                "match_reasons": s.match_reasons,
                "penalty_reasons": s.penalty_reasons,
            }
            for s in scores
        ],
    }


@router.post("/reports/generate")
def generate_report(body: dict, session: Session = Depends(get_session)):
    listing_id = body.get("listing_id")
    if not listing_id:
        raise HTTPException(status_code=422, detail="listing_id required")

    target = session.get(Listing, UUID(listing_id))
    if not target:
        raise HTTPException(status_code=404, detail="Listing not found")

    # 1. Find comps
    comp_scores = comp_matcher.find_comps(target, session, limit=20)
    comp_listings = {
        str(cs.listing_id): session.get(Listing, cs.listing_id)
        for cs in comp_scores
    }

    # 2. Compute valuation
    valuation = compute(ValuationInput(target, comp_scores, comp_listings))

    # 3. Generate report
    top_comps = [
        (comp_scores[i], comp_listings[str(comp_scores[i].listing_id)])
        for i in range(min(5, len(comp_scores)))
        if comp_listings.get(str(comp_scores[i].listing_id))
    ]
    report_output = report_generator.generate(
        report_generator.ReportInput(target, valuation, top_comps)
    )

    # 4. Persist report
    report = Report(
        target_listing_id=target.id,
        verdict=report_output.verdict,
        confidence_level=valuation.confidence_level,
        asking_price=target.asking_price,
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
        risk_flags={"flags": report_output.risk_flags},
        desirability_factors={"factors": report_output.desirability_factors},
        seller_questions={"questions": report_output.seller_questions},
        report_markdown=report_output.report_markdown,
    )
    session.add(report)
    session.flush()  # ensure report row exists before FK refs in comp_matches

    # 5. Persist comp matches
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

    return {"report_id": str(report.id)}
