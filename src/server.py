import asyncio
import json
import os
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

from agent.listingsTool import run_agent

app = Flask(__name__, static_folder=str(Path(__file__).parent / "public"))

PORT        = int(os.environ.get("PORT", 3000))
DATABASE_URL = os.environ.get("DATABASE_URL")


# ── Database helpers ─────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS saved_listings (
                    key  TEXT PRIMARY KEY,
                    data JSONB NOT NULL
                )
            """)
        conn.commit()


def listing_key(l: dict) -> str:
    return (l.get("url") or l.get("title") or "").lower().strip()


def load_saved() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT data FROM saved_listings ORDER BY data->>'title'")
            return [row["data"] for row in cur.fetchall()]


def save_one(listing: dict) -> None:
    key = listing_key(listing)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO saved_listings (key, data)
                VALUES (%s, %s)
                ON CONFLICT (key) DO NOTHING
            """, (key, json.dumps(listing)))
        conn.commit()


def delete_one(key: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM saved_listings WHERE key = %s", (key,))
        conn.commit()


def clear_all() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM saved_listings")
        conn.commit()


# ── Routes ───────────────────────────────────────────────────────────────────

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

    save_one(listing)
    return jsonify({"ok": True})


@app.route("/api/save", methods=["DELETE"])
def unsave_listing():
    data = request.get_json(force=True) or {}
    key  = (data.get("key") or "").lower().strip()

    if not key:
        return jsonify({"error": "key required"}), 400

    delete_one(key)
    return jsonify({"ok": True})


@app.route("/api/save/clear", methods=["POST"])
def clear_saved():
    clear_all()
    return jsonify({"ok": True})


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if DATABASE_URL:
        init_db()
    print(f"Abode UI → http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT)


# Called by gunicorn — init DB on startup
if DATABASE_URL:
    init_db()
