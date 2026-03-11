import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

from scrapers.craigslist import scrape_craigslist
from scrapers.redfin import scrape_apartments
from scrapers.zillow import scrape_zillow

app = Flask(__name__, static_folder=str(Path(__file__).parent / "public"))

PORT = int(os.environ.get("PORT", 3000))


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/search", methods=["POST"])
def search():
    data = request.get_json(force=True) or {}

    sources = data.get("sources", ["craigslist", "apartments", "zillow"])
    bedrooms = data.get("bedrooms")
    min_baths = data.get("minBaths")
    max_rent = data.get("maxRent")
    min_rent = data.get("minRent", 0)

    if not max_rent or not bedrooms:
        return jsonify({"error": "bedrooms and maxRent are required"}), 400

    filters = {
        "maxRent":   int(max_rent),
        "minRent":   int(min_rent),
        "bedrooms":  int(bedrooms),
        "minBaths":  int(min_baths) if min_baths else None,
    }

    scraper_map = {
        "craigslist": ("Craigslist", scrape_craigslist),
        "apartments": ("Redfin",     scrape_apartments),
        "zillow":     ("Zillow",     scrape_zillow),
    }

    selected = [(key, name, fn) for key, (name, fn) in scraper_map.items() if key in sources]

    async def run_all():
        tasks = [fn(filters) for _, _, fn in selected]
        return await asyncio.gather(*tasks, return_exceptions=True)

    settled = asyncio.run(run_all())

    results = {}
    for (key, name, _), outcome in zip(selected, settled):
        if isinstance(outcome, Exception):
            print(f"{name} error: {outcome}")
            results[name] = []
        else:
            results[name] = outcome

    total = sum(len(v) for v in results.values())
    return jsonify({"results": results, "total": total})


if __name__ == "__main__":
    print(f"Apartment Finder UI → http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT)
