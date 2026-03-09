const puppeteer = require("puppeteer-extra");
const StealthPlugin = require("puppeteer-extra-plugin-stealth");
puppeteer.use(StealthPlugin());

async function scrapeApartments({ maxRent, bedrooms, minBaths }) {
  const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  await page.setUserAgent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36");
  const listings = [];
  const bathsParam = minBaths ? `,min-baths=${minBaths}` : "";
  const url = `https://www.redfin.com/neighborhood/28211/IL/Chicago/Lincoln-Park/rentals/filter/max-price=${maxRent},min-beds=${bedrooms}${bathsParam}`;
  try {
    await page.goto(url, { waitUntil: "networkidle2", timeout: 30000 });
    await new Promise(r => setTimeout(r, 4000));
    const results = await page.evaluate(() => {
      return Array.from(document.querySelectorAll(".HomeCardContainer")).map(el => {
        const address =
          el.querySelector(".homeAddressV2")?.innerText?.trim() ||
          el.querySelector("[data-rf-test-id='abp-streetLine']")?.innerText?.trim() ||
          el.querySelector(".street-address")?.innerText?.trim() ||
          el.querySelector(".address")?.innerText?.trim() ||
          el.querySelector("[class*='address' i]")?.innerText?.trim() ||
          "";
        const priceEl = el.querySelector(".homecardV2Price")?.innerText?.trim() || "";
        // For multi-unit cards, extract first price from text
        const priceMatch = (priceEl || el.innerText).match(/\$[\d,]+\/mo/);
        const price = priceMatch ? priceMatch[0] : "";
        const stats = el.querySelector(".HomeStatsV2")?.innerText?.trim() || "";
        const bedsMatch = stats.match(/(\d+)\s*bed/i);
        const bathsMatch = stats.match(/([\d.]+)\s*bath/i);
        const sqftMatch = stats.match(/([\d,]+)\s*sq\s*ft/i);
        return {
          title: address.split("\n")[0].trim() || address,
          price,
          location: address.split("|").pop()?.trim() || address,
          url: el.querySelector("a")?.href || "",
          beds: bedsMatch ? bedsMatch[1] : "",
          baths: bathsMatch ? bathsMatch[1] : "",
          sqft: sqftMatch ? sqftMatch[1] : "",
          source: "Redfin",
          scrapedAt: new Date().toISOString(),
        };
      }).filter(l => l.url && l.price);
    });
    listings.push(...results);
  } catch (err) {
    console.error("Redfin scrape error:", err.message);
  }
  await browser.close();
  return listings;
}

module.exports = { scrapeApartments };
