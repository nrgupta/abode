from datetime import datetime, timezone
from playwright.async_api import async_playwright


async def scrape_craigslist(filters: dict) -> list[dict]:
    max_rent = filters.get("maxRent")
    bedrooms = filters.get("bedrooms")

    br_map = {
        1: "min_bedrooms=1&max_bedrooms=1",
        2: "min_bedrooms=2&max_bedrooms=2",
        3: "min_bedrooms=3",
    }
    br_param = br_map.get(bedrooms, "")
    url = f"https://chicago.craigslist.org/search/apa?max_price={max_rent}&{br_param}#search=1~list~0~0"

    listings = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_selector(".cl-search-result", timeout=10000)

            results = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('.cl-search-result')).map(el => {
                    const hood =
                        el.querySelector('.location .housing-location')?.innerText?.trim() ||
                        el.querySelector('.meta .housing-location')?.innerText?.trim() ||
                        el.querySelector("[data-hook='hood']")?.innerText?.trim() ||
                        el.querySelector('.location')?.innerText?.trim() ||
                        '';
                    const neighborhood = hood.replace(/^\\(|\\)$/g, '').trim();
                    const location = neighborhood ? `${neighborhood}, Chicago, IL` : 'Chicago, IL';

                    const housing = el.querySelector('.housing')?.innerText?.trim() || '';
                    const bedsMatch = housing.match(/(\\d+)\\s*br/i);
                    const bathsMatch = housing.match(/(\\d+(?:\\.\\d+)?)\\s*ba/i);

                    return {
                        title:
                            el.querySelector('a.posting-title .label')?.innerText?.trim() ||
                            el.querySelector('a.posting-title')?.innerText?.trim() ||
                            el.querySelector('.title')?.innerText?.trim() ||
                            '',
                        price:     el.querySelector('.priceinfo')?.innerText?.trim() || '',
                        location,
                        url:       el.querySelector('a.posting-title')?.href || '',
                        beds:      bedsMatch ? bedsMatch[1] : '',
                        baths:     bathsMatch ? bathsMatch[1] : '',
                        source:    'Craigslist',
                        scrapedAt: new Date().toISOString(),
                    };
                });
            }""")

            listings.extend(results)

        except Exception as e:
            print(f"Craigslist scrape error: {e}")

        await browser.close()

    return listings
