import re
from datetime import datetime, timezone
from playwright.async_api import async_playwright


async def scrape_redfin(filters: dict) -> list[dict]:
    max_rent = filters.get("maxRent")
    bedrooms = filters.get("bedrooms")
    min_baths = filters.get("minBaths")

    baths_param = f",min-baths={min_baths}" if min_baths else ""
    url = (
        f"https://www.redfin.com/neighborhood/28211/IL/Chicago/Lincoln-Park"
        f"/rentals/filter/max-price={max_rent},min-beds={bedrooms}{baths_param}"
    )

    listings = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="load", timeout=30000)
            await page.wait_for_timeout(4000)

            results = await page.evaluate("""() => {
                const results = Array.from(document.querySelectorAll('.HomeCardContainer')).map(el => {
                    const address =
                        el.querySelector('.homeAddressV2')?.innerText?.trim() ||
                        el.querySelector("[data-rf-test-id='abp-streetLine']")?.innerText?.trim() ||
                        el.querySelector('.street-address')?.innerText?.trim() ||
                        el.querySelector('.address')?.innerText?.trim() ||
                        el.querySelector("[class*='address' i]")?.innerText?.trim() ||
                        '';
                    const priceEl = el.querySelector('.homecardV2Price')?.innerText?.trim() || '';
                    const priceMatch = (priceEl || el.innerText).match(/\\$[\\d,]+\\/mo/);
                    const price = priceMatch ? priceMatch[0] : '';
                    const stats = el.querySelector('.HomeStatsV2')?.innerText?.trim() || '';
                    const bedsMatch = stats.match(/(\\d+)\\s*bed/i);
                    const bathsMatch = stats.match(/([\\d.]+)\\s*bath/i);
                    const sqftMatch = stats.match(/([\\d,]+)\\s*sq\\s*ft/i);
                    return {
                        title: address.split('\\n')[0].trim() || address,
                        price,
                        location: address.split('|').pop()?.trim() || address,
                        url: el.querySelector('a')?.href || '',
                        beds: bedsMatch ? bedsMatch[1] : '',
                        baths: bathsMatch ? bathsMatch[1] : '',
                        sqft: sqftMatch ? sqftMatch[1] : '',
                        source: 'Redfin',
                        scrapedAt: new Date().toISOString(),
                        _debug_stats: stats,
                    };
                }).filter(l => l.url && l.price);
                return results;
            }""")

            print(f"DEBUG Redfin: Found {len(results)} listings")
            if results:
                print(f"DEBUG Redfin first result stats: {results[0].get('_debug_stats')}")
                print(f"DEBUG Redfin first result: {results[0]}")

            listings.extend(results)

        except Exception as e:
            print(f"Redfin scrape error: {e}")

        await browser.close()

    return listings
