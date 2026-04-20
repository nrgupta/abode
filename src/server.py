import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

from agent.listingsTool import run_agent

app = Flask(__name__, static_folder=str(Path(__file__).parent / "public"))

PORT       = int(os.environ.get("PORT", 3000))
SAVED_FILE = Path(__file__).parent / "saved_listings.json"


# ── Saved listings helpers ──────────────────────────────────────────────────

def load_saved() -> list[dict]:
    if SAVED_FILE.exists():
        try:
            return json.loads(SAVED_FILE.read_text())
        except Exception:
            return []
    return []


def write_saved(listings: list[dict]) -> None:
    SAVED_FILE.write_text(json.dumps(listings, indent=2))


def listing_key(l: dict) -> str:
    return (l.get("url") or l.get("title") or "").lower().strip()


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/search", methods=["POST"])
def search():
    data = request.get_json(force=True) or {}

    sources   = ["zillow"]
    bedrooms  = data.get("bedrooms")
    min_baths = data.get("minBaths")
    max_rent  = data.get("maxRent")
    min_rent  = data.get("minRent", 0)

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

    grouped: dict[str, list] = {}
    for listing in listings:
        source = listing.get("source", "Other")
        grouped.setdefault(source, []).append(listing)

    return jsonify({"results": grouped, "total": len(listings)})


@app.route("/api/saved", methods=["GET"])
def get_saved():
    return jsonify({"listings": load_saved()})


@app.route("/api/save", methods=["POST"])
def save_listing():
    listing = request.get_json(force=True)
    if not listing:
        return jsonify({"error": "No listing provided"}), 400

    saved = load_saved()
    key   = listing_key(listing)

    if not any(listing_key(s) == key for s in saved):
        saved.append(listing)
        write_saved(saved)

    return jsonify({"ok": True, "count": len(saved)})


@app.route("/api/save", methods=["DELETE"])
def unsave_listing():
    data = request.get_json(force=True) or {}
    key  = (data.get("key") or "").lower().strip()

    if not key:
        return jsonify({"error": "key required"}), 400

    saved   = load_saved()
    updated = [s for s in saved if listing_key(s) != key]
    write_saved(updated)

    return jsonify({"ok": True, "count": len(updated)})


@app.route("/api/save/clear", methods=["POST"])
def clear_saved():
    write_saved([])
    return jsonify({"ok": True})


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Abode UI → http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT)
