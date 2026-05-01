from typing import Optional
from app.schemas import ParsedListing


def get_scraper(url: str):
    if "bringatrailer.com" in url:
        from app.scrapers import bat
        return bat
    if "carsandbids.com" in url:
        from app.scrapers import cnb
        return cnb
    if "cargurus.com" in url:
        from app.scrapers import cargurus
        return cargurus
    return None


async def scrape(url: str) -> Optional[ParsedListing]:
    scraper = get_scraper(url)
    if scraper is None:
        return None
    result = await scraper.scrape(url)
    # scrapers return (parsed, http_status, restriction_signal) — extract just parsed
    if isinstance(result, tuple):
        return result[0]
    return result
