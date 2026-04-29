from pydantic import BaseModel, Field
from typing import Optional
from decimal import Decimal


class ParsedListing(BaseModel):
    year: Optional[int] = None
    make: str = "Porsche"
    model: str = "911"
    generation: Optional[str] = None
    trim: Optional[str] = None
    body_style: Optional[str] = None
    transmission: Optional[str] = None
    drivetrain: Optional[str] = None
    mileage: Optional[int] = None
    asking_price: Optional[Decimal] = None
    sold_price: Optional[Decimal] = None
    exterior_color: Optional[str] = None
    interior_color: Optional[str] = None
    location: Optional[str] = None
    seller_type: Optional[str] = None
    vin: Optional[str] = None
    options: list[str] = Field(default_factory=list)
    modifications: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)
    title_status: Optional[str] = None
    accident_reported: Optional[bool] = None
    owner_count: Optional[int] = None
    cpo: Optional[bool] = None
    parser_confidence: float = 0.0
    missing_fields: list[str] = Field(default_factory=list)


class ParseListingRequest(BaseModel):
    raw_text: str
    source_url: Optional[str] = None
