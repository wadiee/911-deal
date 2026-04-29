from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from app.comp_matcher import CompScore
from app.models import Listing


@dataclass
class ValuationInput:
    target: Listing
    scored_comps: list[CompScore]
    comp_listings: dict[str, Listing]


@dataclass
class ValuationResult:
    sold_comp_low: Optional[Decimal]
    sold_comp_high: Optional[Decimal]
    sold_comp_count: int
    active_asking_low: Optional[Decimal]
    active_asking_high: Optional[Decimal]
    active_asking_count: int
    estimated_market_low: Optional[Decimal]
    estimated_market_high: Optional[Decimal]
    recommended_offer_low: Optional[Decimal]
    recommended_offer_high: Optional[Decimal]
    confidence_level: str
    confidence_reason: str


def _round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _weighted_percentile(values: list[float], weights: list[float], pct: float) -> Optional[Decimal]:
    """Compute a weighted percentile. pct is 0–100."""
    if not values:
        return None
    paired = sorted(zip(values, weights), key=lambda x: x[0])
    total_weight = sum(w for _, w in paired)
    if total_weight == 0:
        return None

    target_cumulative = (pct / 100) * total_weight
    cumulative = 0.0
    for value, weight in paired:
        cumulative += weight
        if cumulative >= target_cumulative:
            return _round2(Decimal(str(value)))
    return _round2(Decimal(str(paired[-1][0])))


def _confidence_level(
    sold_count: int,
    active_count: int,
    scored_comps: list[CompScore],
    target: Listing,
    comp_listings: dict[str, Listing],
) -> tuple[str, str]:
    top5 = scored_comps[:5]
    top5_listings = [comp_listings.get(str(s.listing_id)) for s in top5 if comp_listings.get(str(s.listing_id))]

    def all_match(attr: str) -> bool:
        target_val = getattr(target, attr)
        if not target_val:
            return False
        return all(getattr(l, attr) == target_val for l in top5_listings if getattr(l, attr))

    if (
        sold_count >= 5
        and all_match("generation")
        and all_match("trim")
        and all_match("body_style")
    ):
        return "HIGH", (
            f"High confidence: {sold_count} close sold comps found, all matching "
            f"{target.generation} {target.trim} {target.body_style}."
        )

    if sold_count >= 2 or active_count >= 4:
        reason_parts = []
        if sold_count >= 2:
            reason_parts.append(f"{sold_count} sold comps")
        if active_count >= 4:
            reason_parts.append(f"{active_count} active asking comps")
        return "MEDIUM", f"Medium confidence: {' and '.join(reason_parts)} found."

    reasons = []
    if sold_count == 0:
        reasons.append("no confirmed sold comps")
    if active_count < 4:
        reasons.append(f"only {active_count} active comps")
    if not target.transmission:
        reasons.append("transmission unknown")
    return "LOW", f"Low confidence: {'; '.join(reasons)}."


def compute(inp: ValuationInput) -> ValuationResult:
    target = inp.target
    scored_comps = inp.scored_comps
    comp_listings = inp.comp_listings

    # --- Separate sold vs active comps ---
    sold_pairs: list[tuple[float, float]] = []
    active_pairs: list[tuple[float, float]] = []

    for s in scored_comps:
        comp = comp_listings.get(str(s.listing_id))
        if comp is None:
            continue

        price = comp.sold_price or comp.asking_price or comp.last_seen_price
        if price is None:
            continue

        price_f = float(price)

        if comp.price_type == "SOLD_PRICE" and price_f > 0:
            sold_pairs.append((price_f, s.final_weight if s.final_weight > 0 else 0.01))

        elif comp.price_type == "ASKING_PRICE" and comp.status == "ACTIVE" and price_f > 0:
            active_pairs.append((price_f, s.final_weight if s.final_weight > 0 else 0.01))

    sold_count = len(sold_pairs)
    active_count = len(active_pairs)

    # --- Sold comp range (weighted 15th–85th percentile) ---
    sold_low = sold_high = None
    if sold_count >= 2:
        vals, wts = zip(*sold_pairs)
        sold_low = _weighted_percentile(list(vals), list(wts), 15)
        sold_high = _weighted_percentile(list(vals), list(wts), 85)

    # --- Active asking range (weighted 10th–90th percentile) ---
    active_low = active_high = None
    if active_count >= 1:
        vals, wts = zip(*active_pairs)
        active_low = _weighted_percentile(list(vals), list(wts), 10)
        active_high = _weighted_percentile(list(vals), list(wts), 90)

    # --- Estimated market range ---
    est_low = est_high = None

    if sold_count >= 3:
        est_low, est_high = sold_low, sold_high
        if active_count < 3 and est_low and est_high:
            est_low = _round2(est_low * Decimal("1.05"))
            est_high = _round2(est_high * Decimal("1.05"))

    elif active_count >= 3:
        # Active asking prices are optimistic — shift down 6%
        if active_low and active_high:
            est_low = _round2(active_low * Decimal("0.94"))
            est_high = _round2(active_high * Decimal("0.94"))

    elif active_count >= 1 and active_low and active_high:
        # Very sparse — shift down more aggressively
        est_low = _round2(active_low * Decimal("0.90"))
        est_high = _round2(active_high * Decimal("0.92"))

    # --- Recommended offer range ---
    offer_low = offer_high = None

    if est_low and est_high:
        offer_low = est_low
        offer_high = est_high

        # Private seller: room to negotiate
        if target.seller_type == "PRIVATE":
            offer_low = _round2(offer_low * Decimal("0.96"))
            offer_high = _round2(offer_high * Decimal("0.97"))

        # Asking price above market high: push down further
        if target.asking_price and target.asking_price > est_high:
            offer_low = _round2(offer_low * Decimal("0.97"))
            offer_high = _round2(offer_high * Decimal("0.97"))

        # Low confidence: widen
        confidence_level, _ = _confidence_level(sold_count, active_count, scored_comps, target, comp_listings)
        if confidence_level == "LOW":
            offer_low = _round2(offer_low * Decimal("0.95"))
            offer_high = _round2(offer_high * Decimal("1.05"))

        # Floor: never recommend below est_low - 10%
        floor = _round2(est_low * Decimal("0.90"))
        if offer_low < floor:
            offer_low = floor

    confidence_level, confidence_reason = _confidence_level(
        sold_count, active_count, scored_comps, target, comp_listings
    )

    return ValuationResult(
        sold_comp_low=sold_low,
        sold_comp_high=sold_high,
        sold_comp_count=sold_count,
        active_asking_low=active_low,
        active_asking_high=active_high,
        active_asking_count=active_count,
        estimated_market_low=est_low,
        estimated_market_high=est_high,
        recommended_offer_low=offer_low,
        recommended_offer_high=offer_high,
        confidence_level=confidence_level,
        confidence_reason=confidence_reason,
    )
