from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlmodel import Session, select

from app.models import Listing


@dataclass
class CompScore:
    listing_id: UUID
    similarity_score: float
    data_weight: float
    final_weight: float
    match_reasons: list[str] = field(default_factory=list)
    penalty_reasons: list[str] = field(default_factory=list)


def _trim_class(trim: Optional[str]) -> Optional[str]:
    """Group trims into broad classes for cross-trim penalty logic."""
    if trim is None:
        return None
    if trim in ("GT3", "GT3_RS", "GT2", "GT2_RS"):
        return "GT"
    if trim in ("TURBO", "TURBO_S"):
        return "TURBO"
    if trim in ("GTS", "GTS_4"):
        return "GTS"
    if trim in ("CARRERA", "CARRERA_S", "CARRERA_4", "CARRERA_4S", "CARRERA_T", "SPEEDSTER"):
        return "CARRERA"
    if trim in ("TARGA_4", "TARGA_4S"):
        return "TARGA"
    return None


def get_data_weight(comp: Listing) -> float:
    now = datetime.now(timezone.utc)

    # Stale check — last seen > 18 months ago
    if comp.last_seen_at:
        last_seen = comp.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        months_old = (now - last_seen).days / 30
        if months_old > 18:
            return 0.10

    if comp.price_type == "SOLD_PRICE":
        if comp.source in ("bat", "cnb"):
            return 1.00
        if comp.seller_type == "DEALER":
            return 0.80
        return 0.70

    if comp.price_type in ("LAST_SEEN_PRICE", "REMOVED_UNKNOWN"):
        return 0.40

    if comp.price_type == "ASKING_PRICE":
        return 0.25

    return 0.10


def score_comp(target: Listing, comp: Listing) -> CompScore:
    score = 0.0
    bonuses: list[str] = []
    penalties: list[str] = []
    now = datetime.now(timezone.utc)

    # --- Generation ---
    if target.generation and comp.generation:
        if target.generation == comp.generation:
            score += 25
            bonuses.append(f"same generation ({comp.generation})")
        else:
            score -= 30
            penalties.append(f"different generation ({target.generation} vs {comp.generation})")

    # --- Trim ---
    if target.trim and comp.trim:
        if target.trim == comp.trim:
            score += 25
            bonuses.append(f"same trim ({comp.trim})")
        else:
            target_class = _trim_class(target.trim)
            comp_class = _trim_class(comp.trim)
            if target_class != comp_class:
                score -= 20
                penalties.append(f"different trim class ({target.trim} vs {comp.trim})")

    # --- Transmission ---
    if target.transmission and comp.transmission:
        if target.transmission == comp.transmission:
            score += 15
            bonuses.append(f"same transmission ({comp.transmission})")
        else:
            score -= 15
            penalties.append(f"different transmission ({target.transmission} vs {comp.transmission})")

    # --- Body style ---
    if target.body_style and comp.body_style:
        if target.body_style == comp.body_style:
            score += 10
            bonuses.append(f"same body style ({comp.body_style})")

    # --- Mileage ---
    if target.mileage and comp.mileage:
        diff = abs(target.mileage - comp.mileage)
        if diff <= 10_000:
            score += 10
            bonuses.append(f"mileage within 10k miles (diff={diff:,})")
        elif diff > 40_000:
            score -= 20
            penalties.append(f"mileage difference >40k miles (diff={diff:,})")

    # --- Model year ---
    if target.year and comp.year:
        diff = abs(target.year - comp.year)
        if diff <= 2:
            score += 5
            bonuses.append(f"year within 2 years ({comp.year})")

    # --- Seller type ---
    if target.seller_type and comp.seller_type:
        if target.seller_type == comp.seller_type:
            score += 3
            bonuses.append(f"same seller type ({comp.seller_type})")

    # --- Title/accident status ---
    target_clean = target.accident_reported is False and target.title_status in (None, "clean")
    comp_clean = comp.accident_reported is False and comp.title_status in (None, "clean")
    if target_clean == comp_clean:
        score += 5
        bonuses.append("matching title/accident status")
    else:
        score -= 15
        penalties.append("accident or title mismatch")

    # --- Recency ---
    ref_date = comp.date_sold or comp.last_seen_at or comp.date_seen
    if ref_date:
        if ref_date.tzinfo is None:
            ref_date = ref_date.replace(tzinfo=timezone.utc)
        days_old = (now - ref_date).days
        if days_old <= 365:
            score += 7
            bonuses.append(f"recent comp ({days_old} days old)")
        elif days_old > 1095:  # 3 years
            score -= 10
            penalties.append(f"comp is older than 3 years ({days_old} days)")

    # --- Modifications mismatch ---
    target_modified = bool(target.modifications)
    comp_modified = bool(comp.modifications)
    if target_modified != comp_modified:
        score -= 10
        penalties.append("modified vs stock mismatch")

    data_weight = get_data_weight(comp)
    final_weight = score * data_weight

    return CompScore(
        listing_id=comp.id,
        similarity_score=round(score, 2),
        data_weight=round(data_weight, 2),
        final_weight=round(final_weight, 2),
        match_reasons=bonuses,
        penalty_reasons=penalties,
    )


def find_comps(target: Listing, session: Session, limit: int = 20) -> list[CompScore]:
    candidates = session.exec(
        select(Listing).where(
            Listing.make == "Porsche",
            Listing.model == "911",
            Listing.id != target.id,
        )
    ).all()

    scores = [score_comp(target, comp) for comp in candidates]
    scores.sort(key=lambda s: s.final_weight, reverse=True)
    return scores[:limit]
