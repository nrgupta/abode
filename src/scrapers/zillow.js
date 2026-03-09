const https = require("https");

const ZILLOW_API_URL = "https://www.zillow.com/async-create-search-page-state";

// Chicago bounding box
const MAP_BOUNDS = {
  west:  -87.75778635009765,
  east:  -87.52089364990233,
  south: 41.83906339136601,
  north: 42.00969814958818,
};

const MAP_ZOOM = 12;

// Region: Chicago, IL (regionId 17426, regionType 6)
const REGION_SELECTION = [{ regionId: 17426, regionType: 6 }];

// Amenity filter defaults
const FILTER_DEFAULTS = {
  isForSaleByAgent:    false,
  isForSaleByOwner:    false,
  isNewConstruction:   false,
  isComingSoon:        false,
  isAuction:           false,
  isForSaleForeclosure: false,
  inUnitLaundry:       true,
  parkingAvailable:    true,
};

function buildPayload({ maxRent, minRent = 0, minBeds, maxBeds, minBaths = null, maxBaths = null }) {
  return {
    searchQueryState: {
      pagination: {},
      isMapVisible: true,
      mapBounds: MAP_BOUNDS,
      mapZoom: MAP_ZOOM,
      regionSelection: REGION_SELECTION,
      filterState: {
        isForRent:                       { value: true },
        isForSaleByAgent:                { value: FILTER_DEFAULTS.isForSaleByAgent },
        isForSaleByOwner:                { value: FILTER_DEFAULTS.isForSaleByOwner },
        isNewConstruction:               { value: FILTER_DEFAULTS.isNewConstruction },
        isComingSoon:                    { value: FILTER_DEFAULTS.isComingSoon },
        isAuction:                       { value: FILTER_DEFAULTS.isAuction },
        isForSaleForeclosure:            { value: FILTER_DEFAULTS.isForSaleForeclosure },
        monthlyPayment:                  { min: minRent, max: maxRent },
        beds:                            { min: minBeds, max: maxBeds ?? null },
        baths:                           { min: minBaths, max: maxBaths },
        onlyRentalInUnitLaundry:         { value: FILTER_DEFAULTS.inUnitLaundry },
        onlyRentalParkingAvailable:      { value: FILTER_DEFAULTS.parkingAvailable },
      },
      isListVisible: true,
    },
    wants: {
      cat1: ["mapResults"],
    },
    requestId: 2,
    isDebugRequest: false,
  };
}

async function scrapeZillow({ maxRent, minRent = 0, bedrooms, maxBedrooms, minBaths, maxBaths }) {
  const payload = buildPayload({
    maxRent,
    minRent,
    minBeds: bedrooms,
    maxBeds: maxBedrooms ?? bedrooms,
    minBaths,
    maxBaths,
  });

  const body = JSON.stringify(payload);

  const options = {
    method: "PUT",
    headers: {
      "accept":            "*/*",
      "accept-language":   "en-US,en;q=0.9",
      "content-type":      "application/json",
      "content-length":    Buffer.byteLength(body),
      "sec-fetch-dest":    "empty",
      "sec-fetch-mode":    "cors",
      "sec-fetch-site":    "same-origin",
      "user-agent":        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    },
  };

  const json = await new Promise((resolve, reject) => {
    const req = https.request(ZILLOW_API_URL, options, res => {
      let data = "";
      res.on("data", chunk => { data += chunk; });
      res.on("end", () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error("Failed to parse Zillow response: " + e.message)); }
      });
    });
    req.on("error", reject);
    req.write(body);
    req.end();
  });

  const results = json?.cat1?.searchResults?.mapResults || [];
  const listings = [];

  for (const r of results) {
    const price = r.price || r.unformattedPrice || "";
    const numericPrice = parseInt(String(price).replace(/\D/g, ""), 10);
    if (!numericPrice) continue;

    listings.push({
      title:     r.address || "",
      price:     `$${numericPrice}/mo`,
      location:  `${r.addressCity || ""}, ${r.addressState || ""}`,
      url:       `https://www.zillow.com${r.detailUrl || ""}`,
      beds:      r.beds || "",
      baths:     r.baths || "",
      sqft:      r.area || "",
      source:    "Zillow",
      scrapedAt: new Date().toISOString(),
    });
  }

  return listings;
}

module.exports = { scrapeZillow };
