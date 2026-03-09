require("dotenv").config();
const config = require("./config");
const { scrapeCraigslist } = require("./scrapers/craigslist");
const { scrapeApartments } = require("./scrapers/redfin");
const { scrapeZillow } = require("./scrapers/zillow");

async function main() {
  console.log("🏠 Apartment Finder — Starting scrape-only run");
  console.log(`   Filters: ${config.search.bedrooms}BR, max $${config.search.maxRent}/mo`);
  console.log(`   Time: ${new Date().toLocaleString("en-US", { timeZone: "America/Chicago" })}\n`);
  const filters = { maxRent: config.search.maxRent, bedrooms: config.search.bedrooms };
  console.log("🔍 Scraping all sources...");
  const [cl, ap, zl] = await Promise.allSettled([
    scrapeCraigslist(filters),
    scrapeApartments(filters),
    scrapeZillow(filters),
  ]);
  const allListings = [
    ...(cl.status === "fulfilled" ? cl.value : []),
    ...(ap.status === "fulfilled" ? ap.value : []),
    ...(zl.status === "fulfilled" ? zl.value : []),
  ];
  console.log(`📦 Craigslist: ${cl.value?.length??0} | Apartments: ${ap.value?.length??0} | Zillow: ${zl.value?.length??0} | Total: ${allListings.length}`);
  if (allListings.length === 0) { console.error("❌ No listings found."); process.exit(1); }
  console.log("\n📋 Raw listings:\n");
  const bySource = allListings.reduce((acc, l) => {
    (acc[l.source] = acc[l.source] || []).push(l);
    return acc;
  }, {});
  let i = 1;
  for (const [source, listings] of Object.entries(bySource)) {
    console.log(`── ${source} (${listings.length}) ──────────────────────`);
    for (const l of listings) {
      console.log(`[${i++}] ${l.title}`);
      console.log(`    Price: ${l.price} | Location: ${l.location}`);
      if (l.beds) console.log(`    Beds: ${l.beds} | Baths: ${l.baths} | Sqft: ${l.sqft}`);
      console.log(`    URL: ${l.url}`);
      console.log();
    }
  }
  console.log(`✅ Done! Found ${allListings.length} listings total.`);
}

main().catch(err => { console.error("Fatal error:", err); process.exit(1); });
