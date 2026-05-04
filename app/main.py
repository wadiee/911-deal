import logging
from contextlib import asynccontextmanager

import markdown as md_lib
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.routers import public, admin, api

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from scripts.refresh import run_refresh
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_refresh, "interval", hours=12, id="refresh", misfire_grace_time=300)
    scheduler.start()
    logger.info("Refresh scheduler started — runs every 12 hours")
    yield
    scheduler.shutdown()
    logger.info("Refresh scheduler stopped")


app = FastAPI(title="911 Deal Radar", lifespan=lifespan)

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["zip"] = zip
templates.env.filters["markdown"] = lambda text: Markup(md_lib.markdown(text or "", extensions=["nl2br"]))

app.include_router(public.router)
app.include_router(admin.router, prefix="/admin")
app.include_router(api.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
