require("dotenv").config();
const express = require("express");
const path = require("path");
const { scrapeCraigslist } = require("./scrapers/craigslist");
const { scrapeApartments } = require("./scrapers/redfin");
const { scrapeZillow } = require("./scrapers/zillow");

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

app.post("/api/search", async (req, res) => {
  const {
    sources = ["craigslist", "apartments", "zillow"],
    bedrooms,
    minBaths,
    maxRent,
    minRent = 0,
  } = req.body;

  if (!maxRent || !bedrooms) {
    return res.status(400).json({ error: "bedrooms and maxRent are required" });
  }

  const filters = { maxRent: Number(maxRent), minRent: Number(minRent), bedrooms: Number(bedrooms), minBaths: minBaths ? Number(minBaths) : undefined };

  const scrapers = [];
  if (sources.includes("craigslist"))  scrapers.push({ key: "Craigslist",  fn: scrapeCraigslist });
  if (sources.includes("apartments"))  scrapers.push({ key: "Redfin",      fn: scrapeApartments });
  if (sources.includes("zillow"))      scrapers.push({ key: "Zillow",      fn: scrapeZillow });

  const settled = await Promise.allSettled(scrapers.map(s => s.fn(filters)));

  const results = {};
  scrapers.forEach((s, i) => {
    results[s.key] = settled[i].status === "fulfilled" ? settled[i].value : [];
    if (settled[i].status === "rejected") {
      console.error(`${s.key} error:`, settled[i].reason?.message);
    }
  });

  const allListings = Object.values(results).flat();
  res.json({ results, total: allListings.length });
});

app.listen(PORT, () => {
  console.log(`Apartment Finder UI → http://localhost:${PORT}`);
});
