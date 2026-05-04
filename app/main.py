import markdown as md_lib
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from app.routers import public, admin, api

app = FastAPI(title="911 Deal Radar")

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["zip"] = zip
templates.env.filters["markdown"] = lambda text: Markup(md_lib.markdown(text or "", extensions=["nl2br"]))

app.include_router(public.router)
app.include_router(admin.router, prefix="/admin")
app.include_router(api.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
