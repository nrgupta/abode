import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scrapers.craigslist import scrape_craigslist
from scrapers.redfin import scrape_redfin
from scrapers.zillow import scrape_zillow
from config import search2by2, search1by1
from sheets.google_sheets import sync_to_sheets


def deduplicate_listings(listings: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for listing in listings:
        key = (listing.get("url") or listing.get("title") or "").lower().strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(listing)
    return unique


async def run_agent(filters: dict, sources: list[str] | None = None) -> list[dict]:
    if sources is None:
        sources = ["craigslist", "redfin", "zillow"]

    scraper_map = {
        "craigslist": scrape_craigslist,
        "redfin": scrape_redfin,
        "zillow": scrape_zillow,
    }

    selected_scrapers = [(key, scraper_map[key]) for key in sources if key in scraper_map]

    print(f"\nScraping {[k for k, _ in selected_scrapers]}...")
    results = await asyncio.gather(*[fn(filters) for _, fn in selected_scrapers], return_exceptions=True)

    all_listings = []
    for (key, _), result in zip(selected_scrapers, results):
        if isinstance(result, Exception):
            print(f"{key} scraper error: {result}")
        else:
            all_listings.extend(result)

    unique = deduplicate_listings(all_listings)
    print(f"Found {len(unique)} unique listings ({len(all_listings)} total before dedup)")
    return unique


async def run_daily_agent() -> None:
    # Scrape 2by2 apartments
    listings_2by2 = await run_agent(search2by2, sources=["zillow"])
    await sync_to_sheets(listings_2by2, sheet_key="2by2")

    # Scrape 1by1 apartments
    listings_1by1 = await run_agent(search1by1, sources=["zillow"])
    await sync_to_sheets(listings_1by1, sheet_key="1by1")