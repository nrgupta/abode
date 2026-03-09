const puppeteer = require("puppeteer-extra");
const StealthPlugin = require("puppeteer-extra-plugin-stealth");
puppeteer.use(StealthPlugin());

async function scrapeCraigslist({ maxRent, bedrooms }) {
  const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  const listings = [];
  const brMap = { 1: "min_bedrooms=1&max_bedrooms=1", 2: "min_bedrooms=2&max_bedrooms=2", 3: "min_bedrooms=3" };
  const brParam = brMap[bedrooms] || "";
  const url = `https://chicago.craigslist.org/search/apa?max_price=${maxRent}&${brParam}#search=1~list~0~0`;
  try {
    await page.goto(url, { waitUntil: "networkidle2", timeout: 30000 });
    await page.waitForSelector(".cl-search-result", { timeout: 10000 });
    const results = await page.evaluate(() => {
      return Array.from(document.querySelectorAll(".cl-search-result")).map(el => {
        // Craigslist puts the neighborhood in .location > .housing-location or a nested <span>
        const hood =
          el.querySelector(".location .housing-location")?.innerText?.trim() ||
          el.querySelector(".meta .housing-location")?.innerText?.trim() ||
          el.querySelector("[data-hook='hood']")?.innerText?.trim() ||
          el.querySelector(".location")?.innerText?.trim() ||
          "";
        // Strip surrounding parens if present: "(Lincoln Park)" → "Lincoln Park"
        const neighborhood = hood.replace(/^\(|\)$/g, "").trim();
        const location = neighborhood ? `${neighborhood}, Chicago, IL` : "Chicago, IL";
        return {
          title:
            el.querySelector("a.posting-title .label")?.innerText?.trim() ||
            el.querySelector("a.posting-title")?.innerText?.trim() ||
            el.querySelector(".title")?.innerText?.trim() ||
            "",
          price:     el.querySelector(".priceinfo")?.innerText?.trim() || "",
          location,
          url:       el.querySelector("a.posting-title")?.href || "",
          source:    "Craigslist",
          scrapedAt: new Date().toISOString(),
        };
      });
    });
    listings.push(...results);
  } catch (err) {
    console.error("Craigslist scrape error:", err.message);
  }
  await browser.close();
  return listings;
}

module.exports = { scrapeCraigslist };
