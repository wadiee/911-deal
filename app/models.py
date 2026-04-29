import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB


class Listing(SQLModel, table=True):
    __tablename__ = "listings"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source: str
    source_url: Optional[str] = None
    status: str  # ACTIVE, SOLD, NO_SALE, REMOVED_UNKNOWN, WITHDRAWN, EXPIRED, UNKNOWN
    price_type: str  # ASKING_PRICE, SOLD_PRICE, BID_TO_PRICE, PRICE_DROP, LAST_SEEN_PRICE, UNKNOWN_FINAL

    asking_price: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    sold_price: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    last_seen_price: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)

    date_seen: Optional[datetime] = None
    date_sold: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    year: Optional[int] = None
    make: str = "Porsche"
    model: str = "911"
    generation: Optional[str] = None
    trim: Optional[str] = None
    body_style: Optional[str] = None
    transmission: Optional[str] = None
    drivetrain: Optional[str] = None

    mileage: Optional[int] = None
    exterior_color: Optional[str] = None
    interior_color: Optional[str] = None
    location: Optional[str] = None
    seller_type: Optional[str] = None
    vin: Optional[str] = None

    title_status: Optional[str] = None
    accident_reported: Optional[bool] = None
    owner_count: Optional[int] = None
    cpo: Optional[bool] = None

    options: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    modifications: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    raw_text: Optional[str] = None
    normalized_notes: Optional[str] = None
    expert_notes: Optional[str] = None

    comp_quality: Optional[str] = None
    confidence_score: Optional[Decimal] = Field(default=None, max_digits=5, decimal_places=2)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PriceObservation(SQLModel, table=True):
    __tablename__ = "price_observations"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    listing_id: uuid.UUID = Field(foreign_key="listings.id")
    observed_at: datetime
    observed_price: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    observation_type: str  # INITIAL_ASK, PRICE_DROP, PRICE_INCREASE, LAST_SEEN, REMOVED, SOLD_CONFIRMED, NO_SALE
    source_url: Optional[str] = None
    raw_snapshot: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Report(SQLModel, table=True):
    __tablename__ = "reports"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    target_listing_id: uuid.UUID = Field(foreign_key="listings.id")
    report_version: str = "1.0"

    verdict: Optional[str] = None
    confidence_level: Optional[str] = None
    asking_price: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    estimated_low: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    estimated_high: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    recommended_offer_low: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    recommended_offer_high: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)

    sold_comp_summary: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    active_comp_summary: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    risk_flags: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    desirability_factors: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    seller_questions: Optional[dict] = Field(default=None, sa_column=Column(JSONB))

    report_markdown: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CompMatch(SQLModel, table=True):
    __tablename__ = "comp_matches"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    report_id: uuid.UUID = Field(foreign_key="reports.id")
    comp_listing_id: uuid.UUID = Field(foreign_key="listings.id")
    similarity_score: Decimal = Field(max_digits=5, decimal_places=2)
    data_weight: Decimal = Field(max_digits=5, decimal_places=2)
    final_weight: Decimal = Field(max_digits=5, decimal_places=2)
    match_reason: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EmailCapture(SQLModel, table=True):
    __tablename__ = "email_captures"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str
    report_id: Optional[uuid.UUID] = Field(default=None, foreign_key="reports.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
