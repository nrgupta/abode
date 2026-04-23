import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone

ZILLOW_API_URL = "https://www.zillow.com/async-create-search-page-state"

# Ideal Living Area bounding box
MAP_BOUNDS = {
    "west":  -87.68248435944328,
    "east":  -87.61708137482414,
    "south": 41.90064568672503,
    "north": 41.944582838604454,
}

MAP_ZOOM = 12

# Region: Chicago, IL (regionId 17426, regionType 6)
REGION_SELECTION = [{"regionId": 17426, "regionType": 6}]

FILTER_DEFAULTS = {
    "isForSaleByAgent":    False,
    "isForSaleByOwner":    False,
    "isNewConstruction":   False,
    "isComingSoon":        False,
    "isAuction":           False,
    "isForSaleForeclosure": False,
    "inUnitLaundry":       True,
    "parkingAvailable":    True,
}


def build_payload(max_rent, min_rent=0, min_beds=None, max_beds=None, min_baths=None, max_baths=None, min_sqft=None, max_sqft=None):
    filter_state = {
        "isForRent":                  {"value": True},
        "isForSaleByAgent":           {"value": FILTER_DEFAULTS["isForSaleByAgent"]},
        "isForSaleByOwner":           {"value": FILTER_DEFAULTS["isForSaleByOwner"]},
        "isNewConstruction":          {"value": FILTER_DEFAULTS["isNewConstruction"]},
        "isComingSoon":               {"value": FILTER_DEFAULTS["isComingSoon"]},
        "isAuction":                  {"value": FILTER_DEFAULTS["isAuction"]},
        "isForSaleForeclosure":       {"value": FILTER_DEFAULTS["isForSaleForeclosure"]},
        "monthlyPayment":             {"min": min_rent, "max": max_rent},
        "beds":                       {"min": min_beds, "max": max_beds},
        "baths":                      {"min": min_baths, "max": max_baths},
        "onlyRentalInUnitLaundry":    {"value": FILTER_DEFAULTS["inUnitLaundry"]},
        "onlyRentalParkingAvailable": {"value": FILTER_DEFAULTS["parkingAvailable"]},
    }

    if min_sqft or max_sqft:
        filter_state["sqft"] = {k: v for k, v in {"min": min_sqft, "max": max_sqft}.items() if v is not None}

    return {
        "searchQueryState": {
            "pagination": {},
            "isMapVisible": True,
            "mapBounds": MAP_BOUNDS,
            "mapZoom": MAP_ZOOM,
            "regionSelection": REGION_SELECTION,
            "filterState": filter_state,
            "isListVisible": True,
        },
        "wants": {
            "cat1": ["mapResults"],
        },
        "requestId": 2,
        "isDebugRequest": False,
    }


async def scrape_zillow(filters: dict) -> list[dict]:
    max_rent = filters.get("maxRent")
    min_rent = filters.get("minRent", 0)
    bedrooms = filters.get("bedrooms")
    max_bedrooms = filters.get("maxBedrooms", bedrooms)
    min_baths = filters.get("minBaths")
    max_baths = filters.get("maxBaths")
    min_sqft = filters.get("minSqft")
    max_sqft = filters.get("maxSqft")

    payload = build_payload(
        max_rent=max_rent,
        min_rent=min_rent,
        min_beds=bedrooms,
        max_beds=max_bedrooms,
        min_baths=min_baths,
        max_baths=max_baths,
        min_sqft=min_sqft,
        max_sqft=max_sqft,
    )

    body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        ZILLOW_API_URL,
        data=body,
        method="PUT",
        headers={
            "accept":          "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type":    "application/json",
            "content-length":  str(len(body)),
            "sec-fetch-dest":  "empty",
            "sec-fetch-mode":  "cors",
            "sec-fetch-site":  "same-origin",
            "user-agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        },
    )

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Zillow request error: {e}")
        return []

    results = (data.get("cat1") or {}).get("searchResults", {}).get("mapResults", [])
    listings = []

    for r in results:
        price_raw = r.get("price") or r.get("unformattedPrice") or ""
        numeric_price = re.sub(r"\D", "", str(price_raw))
        if not numeric_price:
            continue

        listing = {
            "title":     r.get("address", ""),
            "price":     f"${numeric_price}/mo",
            "location":  r.get("address", ""),
            "url":       f"https://www.zillow.com{r.get('detailUrl', '')}",
            "beds":      r.get("minBeds", ""),
            "baths":     r.get("minBaths", ""),
            "sqft":      r.get("minArea", ""),
            "image":     r.get("imgSrc", ""),
            "source":    "Zillow",
            "scrapedAt": datetime.now(timezone.utc).isoformat(),
        }
        # Store lat/lng if available — used by amenities endpoint to skip geocoding
        lat = r.get("latLong", {}).get("latitude") or r.get("latitude")
        lng = r.get("latLong", {}).get("longitude") or r.get("longitude")
        if lat and lng:
            listing["lat"] = lat
            listing["lng"] = lng
        listings.append(listing)

    return listings
