#!/usr/bin/env python3
import asyncio
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

import config
from scrapers.craigslist import scrape_craigslist
from scrapers.redfin import scrape_apartments
from scrapers.zillow import scrape_zillow


async def main():
    chicago_time = datetime.now(ZoneInfo("America/Chicago")).strftime("%c")
    print("Apartment Finder — Starting scrape-only run")
    print(f"   Filters: {config.search['bedrooms']}BR, max ${config.search['maxRent']}/mo")
    print(f"   Time: {chicago_time}\n")

    filters = {"maxRent": config.search["maxRent"], "bedrooms": config.search["bedrooms"]}

    print("Scraping all sources...")
    cl, ap, zl = await asyncio.gather(
        scrape_craigslist(filters),
        scrape_apartments(filters),
        scrape_zillow(filters),
        return_exceptions=True,
    )

    cl_listings = cl if not isinstance(cl, Exception) else []
    ap_listings = ap if not isinstance(ap, Exception) else []
    zl_listings = zl if not isinstance(zl, Exception) else []

    all_listings = cl_listings + ap_listings + zl_listings

    print(
        f"Craigslist: {len(cl_listings)} | "
        f"Redfin: {len(ap_listings)} | "
        f"Zillow: {len(zl_listings)} | "
        f"Total: {len(all_listings)}"
    )

    if not all_listings:
        print("No listings found.")
        sys.exit(1)

    print("\nRaw listings:\n")

    by_source: dict[str, list] = {}
    for listing in all_listings:
        by_source.setdefault(listing["source"], []).append(listing)

    i = 1
    for source, listings in by_source.items():
        print(f"── {source} ({len(listings)}) ──────────────────────")
        for listing in listings:
            print(f"[{i}] {listing['title']}")
            print(f"    Price: {listing['price']} | Location: {listing['location']}")
            if listing.get("beds"):
                print(f"    Beds: {listing['beds']} | Baths: {listing['baths']} | Sqft: {listing['sqft']}")
            print(f"    URL: {listing['url']}")
            print()
            i += 1

    print(f"Done! Found {len(all_listings)} listings total.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
