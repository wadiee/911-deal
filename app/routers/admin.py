import hashlib
import hmac
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import settings
from app.database import get_session
from app.models import EmailCapture, Listing, Report

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

COOKIE_NAME = "admin_token"
COOKIE_MAX_AGE = 60 * 60 * 8  # 8 hours


class NotAuthenticated(Exception):
    pass


def _make_token() -> str:
    return hmac.new(settings.admin_secret.encode(), b"admin-authenticated", hashlib.sha256).hexdigest()


def _verify_token(token: str) -> bool:
    return hmac.compare_digest(token, _make_token())


def require_admin(request: Request) -> None:
    token = request.cookies.get(COOKIE_NAME, "")
    if not _verify_token(token):
        raise NotAuthenticated()


@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse(request, "admin/login.html", {})


@router.post("/login")
def login_post(request: Request, password: str = Form()):
    if not hmac.compare_digest(password, settings.admin_secret):
        return templates.TemplateResponse(request, "admin/login.html", {"error": "Invalid password"})
    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(COOKIE_NAME, _make_token(), max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax")
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("", response_class=HTMLResponse)
def admin_index(request: Request, _: None = Depends(require_admin), session: Session = Depends(get_session)):
    listing_count = len(session.exec(select(Listing)).all())
    report_count = len(session.exec(select(Report)).all())
    subscriber_count = len(session.exec(select(EmailCapture)).all())
    return templates.TemplateResponse(request, "admin/index.html", {
        "listing_count": listing_count,
        "report_count": report_count,
        "subscriber_count": subscriber_count,
    })

VALID_STATUSES = ["ACTIVE", "SOLD", "NO_SALE", "REMOVED_UNKNOWN", "WITHDRAWN", "EXPIRED", "UNKNOWN"]
VALID_PRICE_TYPES = ["ASKING_PRICE", "SOLD_PRICE", "BID_TO_PRICE", "PRICE_DROP", "LAST_SEEN_PRICE", "UNKNOWN_FINAL"]
VALID_GENERATIONS = ["991.1", "991.2", "992.1", "992.2"]
VALID_TRIMS = ["CARRERA", "CARRERA_S", "CARRERA_4", "CARRERA_4S", "GTS", "GTS_4", "TARGA_4", "TARGA_4S",
               "GT3", "GT3_RS", "GT3_TOURING", "TURBO", "TURBO_S", "TURBO_CABRIOLET", "TURBO_S_CABRIOLET"]
VALID_BODY_STYLES = ["COUPE", "CABRIOLET", "TARGA"]
VALID_TRANSMISSIONS = ["PDK", "MANUAL"]
VALID_DRIVETRAINS = ["RWD", "AWD"]
VALID_SELLER_TYPES = ["DEALER", "PRIVATE", "AUCTION", "CPO"]
VALID_COMP_QUALITIES = ["HIGH", "MEDIUM", "LOW"]


def _opt_str(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    s = val.strip()
    return s if s else None


def _opt_decimal(val: Optional[str]) -> Optional[Decimal]:
    if not val or not val.strip():
        return None
    try:
        return Decimal(val.strip())
    except InvalidOperation:
        return None


def _opt_int(val: Optional[str]) -> Optional[int]:
    if not val or not val.strip():
        return None
    try:
        return int(val.strip())
    except ValueError:
        return None


@router.get("/subscribers", response_class=HTMLResponse)
def subscriber_list(
    request: Request,
    _: None = Depends(require_admin),
    session: Session = Depends(get_session),
):
    captures = session.exec(
        select(EmailCapture).order_by(EmailCapture.created_at.desc())
    ).all()
    report_ids = {str(c.report_id) for c in captures if c.report_id}
    target_listings = {}
    for rid in report_ids:
        from uuid import UUID as _UUID
        report = session.get(Report, _UUID(rid))
        if report:
            listing = session.get(Listing, report.target_listing_id)
            target_listings[rid] = listing
    return templates.TemplateResponse(request, "admin/subscribers.html", {
        "captures": captures,
        "target_listings": target_listings,
    })


@router.get("/reports", response_class=HTMLResponse)
def report_list(
    request: Request,
    page: int = 1,
    _: None = Depends(require_admin),
    session: Session = Depends(get_session),
):
    page_size = 50
    offset = (page - 1) * page_size
    reports = session.exec(
        select(Report).order_by(Report.created_at.desc()).offset(offset).limit(page_size + 1)
    ).all()
    has_next = len(reports) > page_size
    target_listings = {
        str(r.target_listing_id): session.get(Listing, r.target_listing_id)
        for r in reports[:page_size]
    }
    return templates.TemplateResponse(request, "admin/reports.html", {
        "reports": reports[:page_size],
        "target_listings": target_listings,
        "page": page,
        "has_next": has_next,
    })


@router.get("/listings", response_class=HTMLResponse)
def listing_list(
    request: Request,
    page: int = 1,
    _: None = Depends(require_admin),
    session: Session = Depends(get_session),
):
    page_size = 50
    offset = (page - 1) * page_size
    listings = session.exec(
        select(Listing).order_by(Listing.created_at.desc()).offset(offset).limit(page_size + 1)
    ).all()
    has_next = len(listings) > page_size
    return templates.TemplateResponse(request, "admin/listings.html", {
        "listings": listings[:page_size],
        "page": page,
        "has_next": has_next,
    })


@router.get("/listings/{listing_id}", response_class=HTMLResponse)
def listing_edit(
    listing_id: str,
    request: Request,
    _: None = Depends(require_admin),
    session: Session = Depends(get_session),
    saved: bool = False,
):
    listing = session.get(Listing, UUID(listing_id))
    if not listing:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "admin/listing_edit.html", {
        "listing": listing,
        "saved": saved,
        "valid_statuses": VALID_STATUSES,
        "valid_price_types": VALID_PRICE_TYPES,
        "valid_generations": VALID_GENERATIONS,
        "valid_trims": VALID_TRIMS,
        "valid_body_styles": VALID_BODY_STYLES,
        "valid_transmissions": VALID_TRANSMISSIONS,
        "valid_drivetrains": VALID_DRIVETRAINS,
        "valid_seller_types": VALID_SELLER_TYPES,
        "valid_comp_qualities": VALID_COMP_QUALITIES,
    })


@router.post("/listings/{listing_id}", response_class=HTMLResponse)
def listing_update(
    listing_id: str,
    request: Request,
    _: None = Depends(require_admin),
    session: Session = Depends(get_session),
    source: Optional[str] = Form(default=None),
    source_url: Optional[str] = Form(default=None),
    status: Optional[str] = Form(default=None),
    price_type: Optional[str] = Form(default=None),
    asking_price: Optional[str] = Form(default=None),
    sold_price: Optional[str] = Form(default=None),
    last_seen_price: Optional[str] = Form(default=None),
    year: Optional[str] = Form(default=None),
    generation: Optional[str] = Form(default=None),
    trim: Optional[str] = Form(default=None),
    body_style: Optional[str] = Form(default=None),
    transmission: Optional[str] = Form(default=None),
    drivetrain: Optional[str] = Form(default=None),
    mileage: Optional[str] = Form(default=None),
    exterior_color: Optional[str] = Form(default=None),
    interior_color: Optional[str] = Form(default=None),
    location: Optional[str] = Form(default=None),
    seller_type: Optional[str] = Form(default=None),
    vin: Optional[str] = Form(default=None),
    title_status: Optional[str] = Form(default=None),
    accident_reported: Optional[str] = Form(default=None),
    owner_count: Optional[str] = Form(default=None),
    cpo: Optional[str] = Form(default=None),
    comp_quality: Optional[str] = Form(default=None),
    expert_notes: Optional[str] = Form(default=None),
    normalized_notes: Optional[str] = Form(default=None),
):
    listing = session.get(Listing, UUID(listing_id))
    if not listing:
        raise HTTPException(status_code=404)

    if source is not None:
        listing.source = source.strip()
    listing.source_url = _opt_str(source_url)
    if status and status in VALID_STATUSES:
        listing.status = status
    if price_type and price_type in VALID_PRICE_TYPES:
        listing.price_type = price_type
    listing.asking_price = _opt_decimal(asking_price)
    listing.sold_price = _opt_decimal(sold_price)
    listing.last_seen_price = _opt_decimal(last_seen_price)
    listing.year = _opt_int(year)
    listing.generation = _opt_str(generation) if generation not in ("", None) else None
    listing.trim = _opt_str(trim) if trim not in ("", None) else None
    listing.body_style = _opt_str(body_style) if body_style not in ("", None) else None
    listing.transmission = _opt_str(transmission) if transmission not in ("", None) else None
    listing.drivetrain = _opt_str(drivetrain) if drivetrain not in ("", None) else None
    listing.mileage = _opt_int(mileage)
    listing.exterior_color = _opt_str(exterior_color)
    listing.interior_color = _opt_str(interior_color)
    listing.location = _opt_str(location)
    listing.seller_type = _opt_str(seller_type) if seller_type not in ("", None) else None
    listing.vin = _opt_str(vin)
    listing.title_status = _opt_str(title_status)
    listing.accident_reported = True if accident_reported == "true" else (False if accident_reported == "false" else None)
    listing.owner_count = _opt_int(owner_count)
    listing.cpo = True if cpo == "true" else (False if cpo == "false" else None)
    listing.comp_quality = _opt_str(comp_quality) if comp_quality not in ("", None) else None
    listing.expert_notes = _opt_str(expert_notes)
    listing.normalized_notes = _opt_str(normalized_notes)
    listing.updated_at = datetime.utcnow()

    session.add(listing)
    session.commit()

    return RedirectResponse(url=f"/admin/listings/{listing_id}?saved=true", status_code=303)
