from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.comp_matcher import CompScore
from app.models import Listing
from app.valuation_service import ValuationResult


@dataclass
class ReportInput:
    target: Listing
    valuation: ValuationResult
    top_comps: list[tuple[CompScore, Listing]]


@dataclass
class ReportOutput:
    verdict: str
    risk_flags: list[str]
    desirability_factors: list[str]
    seller_questions: list[str]
    report_markdown: str


def _fmt(val) -> str:
    if val is None:
        return "N/A"
    return f"${float(val):,.0f}"


def _verdict(target: Listing, valuation: ValuationResult) -> str:
    asking = target.asking_price
    low = valuation.estimated_market_low
    high = valuation.estimated_market_high

    if asking is None or low is None or high is None:
        return "Insufficient data to assess"

    asking_f = float(asking)
    low_f = float(low)
    high_f = float(high)

    if asking_f < low_f * 0.95:
        return "Strong value — priced well below market"
    if asking_f < low_f:
        return "Fair deal — below market estimate"
    if asking_f <= high_f:
        return "Fair deal"
    if asking_f <= high_f * 1.05:
        return "Slightly above market"
    if asking_f <= high_f * 1.15:
        return "Overpriced"
    return "Significantly overpriced"


def _risk_flags(target: Listing, valuation: ValuationResult) -> list[str]:
    flags = []

    if target.accident_reported:
        flags.append("Accident reported — request full repair documentation")

    if target.title_status and target.title_status not in ("CLEAN", "clean"):
        flags.append(f"Non-clean title status: {target.title_status}")

    if target.owner_count is not None:
        if target.owner_count >= 4:
            flags.append(f"Many prior owners ({target.owner_count})")
        elif target.owner_count == 3:
            flags.append("3 prior owners")

    mileage = target.mileage
    if mileage:
        if mileage > 80000:
            flags.append(f"High mileage ({int(mileage):,} mi)")
        elif mileage > 60000:
            flags.append(f"Above-average mileage for year ({int(mileage):,} mi)")

    if target.modifications and len(target.modifications) > 0:
        mods = ", ".join(str(m) for m in target.modifications[:3])
        flags.append(f"Modified: {mods}")

    if target.seller_type == "DEALER":
        flags.append("Dealer listing — typically less negotiation room than private sale")

    low = valuation.estimated_market_low
    high = valuation.estimated_market_high
    asking = target.asking_price
    if asking and high and float(asking) > float(high) * 1.1:
        flags.append(
            f"Asking price ({_fmt(asking)}) is more than 10% above market high ({_fmt(high)})"
        )

    if valuation.confidence_level == "LOW":
        flags.append("Limited comp data — price estimate has low confidence")

    return flags


def _desirability(target: Listing) -> list[str]:
    factors = []

    if target.transmission == "MANUAL":
        factors.append("Manual transmission — significantly more desirable and commands a premium")

    if target.cpo:
        factors.append("Certified Pre-Owned — remaining factory warranty coverage")

    mileage = target.mileage
    if mileage:
        if mileage < 20000:
            factors.append(f"Very low mileage ({int(mileage):,} mi)")
        elif mileage < 40000:
            factors.append(f"Low mileage ({int(mileage):,} mi)")

    if not target.accident_reported and target.title_status in (None, "CLEAN"):
        factors.append("Clean title, no accidents reported")

    if target.owner_count == 1:
        factors.append("Single previous owner")

    if target.trim in ("GT3", "GT3_RS", "GT2_RS", "GT2"):
        factors.append(f"GT-spec trim ({target.trim}) — limited production, high collector value")
    elif target.trim in ("TURBO_S", "TURBO"):
        factors.append("Twin-turbocharged model — higher performance ceiling")

    notable_options = {
        "sport exhaust": "Sport exhaust system",
        "sport chrono": "Sport Chrono package",
        "pccb": "Porsche Ceramic Composite Brakes (PCCB)",
        "pdcc": "PDCC active anti-roll system",
        "paint to sample": "Paint-to-Sample color",
        "pts": "Paint-to-Sample color",
        "bucket": "Sport bucket seats",
        "burmester": "Burmester audio",
        "bose": "Bose audio",
        "lift": "Front axle lift system",
        "pasm": "PASM sport suspension",
        "carbon": "Carbon fiber trim package",
    }
    seen_labels: set[str] = set()
    for opt in (target.options or []):
        opt_lower = str(opt).lower()
        for key, label in notable_options.items():
            if key in opt_lower and label not in seen_labels:
                factors.append(label)
                seen_labels.add(label)
                break

    return factors


def _seller_questions(target: Listing, valuation: ValuationResult) -> list[str]:
    questions = []

    questions.append("Can you share the full service history and maintenance records?")

    if target.transmission == "MANUAL":
        questions.append("What is the condition of the clutch? Has it been replaced?")

    if target.accident_reported:
        questions.append(
            "Can you provide CARFAX, repair documentation, and a post-repair inspection report?"
        )

    if target.modifications and len(target.modifications) > 0:
        questions.append(
            "Are all modifications fully documented, and can they be reversed to stock?"
        )

    if not target.owner_count:
        questions.append("How many previous owners has the car had?")

    if target.mileage and target.mileage > 50000:
        questions.append(
            "Are there any deferred or upcoming maintenance items (fluids, brakes, tires)?"
        )

    questions.append("Has the car ever been used on a track?")
    questions.append("When were the tires last replaced, and what brand/spec?")

    if target.cpo:
        questions.append(
            "Is the CPO warranty still active, and is it transferable to the new owner?"
        )

    if not target.mileage:
        questions.append("What is the current odometer reading?")

    if valuation.confidence_level == "LOW":
        questions.append(
            "What comparable cars did you use to arrive at this asking price?"
        )

    return questions


def _markdown(
    target: Listing,
    valuation: ValuationResult,
    top_comps: list[tuple[CompScore, Listing]],
    verdict: str,
    risk_flags: list[str],
    desirability: list[str],
) -> str:
    v = valuation
    lines: list[str] = []

    lines.append(f"## {target.year} Porsche 911 {target.trim} {target.body_style}")
    lines.append("")

    lines.append("### Summary")
    lines.append(f"**Verdict: {verdict}**")
    lines.append("")
    lines.append(
        f"Asking price: **{_fmt(target.asking_price)}** · "
        f"Market estimate: **{_fmt(v.estimated_market_low)} – {_fmt(v.estimated_market_high)}** · "
        f"Confidence: **{v.confidence_level}**"
    )
    lines.append(f"_{v.confidence_reason}_")
    lines.append("")

    lines.append("### Market Context")
    if v.sold_comp_count > 0:
        lines.append(
            f"- {v.sold_comp_count} confirmed sold comps: "
            f"{_fmt(v.sold_comp_low)} – {_fmt(v.sold_comp_high)}"
        )
    else:
        lines.append("- No confirmed sold comps found in database")
    if v.active_asking_count > 0:
        lines.append(
            f"- {v.active_asking_count} active asking comps: "
            f"{_fmt(v.active_asking_low)} – {_fmt(v.active_asking_high)}"
        )
    if v.recommended_offer_low and v.recommended_offer_high:
        lines.append(
            f"- Recommended offer range: "
            f"{_fmt(v.recommended_offer_low)} – {_fmt(v.recommended_offer_high)}"
        )
    lines.append("")

    if top_comps:
        lines.append("### Comps Used")
        for score, comp in top_comps:
            price = comp.sold_price or comp.asking_price
            price_label = f"sold {_fmt(price)}" if comp.sold_price else f"asking {_fmt(price)}"
            lines.append(
                f"- {comp.year} {comp.trim} {comp.body_style} · "
                f"{int(comp.mileage or 0):,} mi · {price_label} · "
                f"score {score.similarity_score}"
            )
        lines.append("")

    if desirability:
        lines.append("### Desirability")
        for f in desirability:
            lines.append(f"- {f}")
        lines.append("")

    if risk_flags:
        lines.append("### Risk Flags")
        for f in risk_flags:
            lines.append(f"- {f}")
        lines.append("")

    lines.append("### Deal Advice")
    asking_f = float(target.asking_price) if target.asking_price else None
    low_f = float(v.estimated_market_low) if v.estimated_market_low else None
    high_f = float(v.estimated_market_high) if v.estimated_market_high else None

    if asking_f is None or low_f is None or high_f is None:
        lines.append(
            "Insufficient comp data to produce a specific offer recommendation. "
            "Gather more comp data before proceeding."
        )
    elif asking_f < low_f * 0.95:
        lines.append(
            f"This car is priced well below comparable sales. Verify no undisclosed issues "
            f"exist — if the inspection is clean, this is an unusually strong opportunity. "
            f"Offer range: **{_fmt(v.recommended_offer_low)} – {_fmt(v.recommended_offer_high)}**."
        )
    elif asking_f <= high_f:
        lines.append(
            f"This listing falls within the expected market range. Negotiate from the lower "
            f"end of the estimate. "
            f"Offer range: **{_fmt(v.recommended_offer_low)} – {_fmt(v.recommended_offer_high)}**."
        )
    elif asking_f <= high_f * 1.1:
        lines.append(
            f"Asking price is slightly above market. Push back toward the market high. "
            f"Offer range: **{_fmt(v.recommended_offer_low)} – {_fmt(v.recommended_offer_high)}**."
        )
    else:
        lines.append(
            f"Asking price is materially above comparables. Either the seller expects premium "
            f"offers or is unaware of the current market. "
            f"Offer range: **{_fmt(v.recommended_offer_low)} – {_fmt(v.recommended_offer_high)}** "
            f"if you still want to proceed."
        )

    return "\n".join(lines)


def generate(inp: ReportInput) -> ReportOutput:
    verdict = _verdict(inp.target, inp.valuation)
    risk_flags = _risk_flags(inp.target, inp.valuation)
    desirability = _desirability(inp.target)
    questions = _seller_questions(inp.target, inp.valuation)
    markdown = _markdown(inp.target, inp.valuation, inp.top_comps, verdict, risk_flags, desirability)

    return ReportOutput(
        verdict=verdict,
        risk_flags=risk_flags,
        desirability_factors=desirability,
        seller_questions=questions,
        report_markdown=markdown,
    )
