import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

from agent.listingsTool import run_agent

app = Flask(__name__, static_folder=str(Path(__file__).parent / "public"))

PORT = int(os.environ.get("PORT", 3000))


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/search", methods=["POST"])
def search():
    data = request.get_json(force=True) or {}

    sources = data.get("sources", ["craigslist", "redfin", "zillow"])
    bedrooms = data.get("bedrooms")
    min_baths = data.get("minBaths")
    max_rent = data.get("maxRent")
    min_rent = data.get("minRent", 0)

    if not max_rent or not bedrooms:
        return jsonify({"error": "bedrooms and maxRent are required"}), 400

    filters = {
        "maxRent":  int(max_rent),
        "minRent":  int(min_rent),
        "bedrooms": int(bedrooms),
        "minBaths": int(min_baths) if min_baths else None,
    }

    try:
        listings = asyncio.run(run_agent(filters, sources))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    grouped = {}
    for listing in listings:
        source = listing.get("source", "Other")
        grouped.setdefault(source, []).append(listing)

    total = len(listings)
    return jsonify({"results": grouped, "total": total})


if __name__ == "__main__":
    print(f"Apartment Finder UI → http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT)
