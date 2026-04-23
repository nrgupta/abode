import asyncio
import hashlib
import json
import math
import os
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, session

load_dotenv()

from agent.listingsTool import run_agent

app = Flask(__name__, static_folder=str(Path(__file__).parent / "public"))

PORT         = int(os.environ.get("PORT", 3000))
DATABASE_URL = os.environ.get("DATABASE_URL")

# Secret key for signing session cookies — set SESSION_SECRET in env for production
app.secret_key = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)

# How long (in seconds) cached search results are considered fresh (default: 4 hours)
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", 4 * 60 * 60))


# ── Database helpers ─────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            SERIAL PRIMARY KEY,
                    email         TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS saved_listings (
                    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    key      TEXT NOT NULL,
                    data     JSONB NOT NULL,
                    PRIMARY KEY (user_id, key)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS passed_listings (
                    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    key      TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    cache_key   TEXT PRIMARY KEY,
                    results     JSONB NOT NULL,
                    cached_at   TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
        conn.commit()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def current_user_id() -> int | None:
    return session.get("user_id")


def require_auth():
    """Return (user_id, None) or (None, error_response)."""
    uid = current_user_id()
    if not uid:
        return None, (jsonify({"error": "Not authenticated"}), 401)
    return uid, None


# ── User DB helpers ───────────────────────────────────────────────────────────

def get_user_by_email(email: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE email = %s", (email.lower().strip(),))
            return cur.fetchone()


def create_user(email: str, password: str) -> dict:
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING *",
                (email.lower().strip(), hashed),
            )
            user = cur.fetchone()
        conn.commit()
    return user


# ── Saved listings helpers ────────────────────────────────────────────────────

def listing_key(l: dict) -> str:
    return (l.get("url") or l.get("title") or "").lower().strip()


def load_saved(user_id: int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT data FROM saved_listings WHERE user_id = %s ORDER BY data->>'title'",
                (user_id,),
            )
            return [row["data"] for row in cur.fetchall()]


def save_one(user_id: int, listing: dict) -> None:
    key = listing_key(listing)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO saved_listings (user_id, key, data)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, key) DO NOTHING
            """, (user_id, key, json.dumps(listing)))
        conn.commit()


def delete_one(user_id: int, key: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM saved_listings WHERE user_id = %s AND key = %s",
                (user_id, key),
            )
        conn.commit()


def clear_all(user_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM saved_listings WHERE user_id = %s", (user_id,))
        conn.commit()


# ── Passed listings helpers ───────────────────────────────────────────────────

def load_passed_keys(user_id: int) -> list[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key FROM passed_listings WHERE user_id = %s", (user_id,))
            return [row[0] for row in cur.fetchall()]


def pass_one(user_id: int, key: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO passed_listings (user_id, key)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
            """, (user_id, key))
        conn.commit()


# ── Search cache helpers ──────────────────────────────────────────────────────

def _cache_key(filters: dict) -> str:
    """Deterministic hash of the search filters used as the cache key."""
    canonical = json.dumps(filters, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def cache_get(filters: dict) -> list[dict] | None:
    """Return cached results if they exist and are within TTL, else None."""
    if not DATABASE_URL:
        return None
    key = _cache_key(filters)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT results, cached_at
                FROM search_cache
                WHERE cache_key = %s
            """, (key,))
            row = cur.fetchone()
    if not row:
        return None
    age = (datetime.now(timezone.utc) - row["cached_at"]).total_seconds()
    if age > CACHE_TTL_SECONDS:
        return None
    return row["results"]


def cache_set(filters: dict, results: list[dict]) -> None:
    """Persist search results to the cache."""
    if not DATABASE_URL:
        return
    key = _cache_key(filters)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO search_cache (cache_key, results, cached_at)
                VALUES (%s, %s, now())
                ON CONFLICT (cache_key) DO UPDATE
                    SET results   = EXCLUDED.results,
                        cached_at = EXCLUDED.cached_at
            """, (key, json.dumps(results)))
        conn.commit()


def cache_clear() -> None:
    """Delete all cached search results."""
    if not DATABASE_URL:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM search_cache")
        conn.commit()


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/api/signup", methods=["POST"])
def signup():
    data     = request.get_json(force=True) or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    if get_user_by_email(email):
        return jsonify({"error": "An account with that email already exists"}), 409

    user = create_user(email, password)
    session["user_id"] = user["id"]
    return jsonify({"ok": True, "email": user["email"]})


@app.route("/api/login", methods=["POST"])
def login():
    data     = request.get_json(force=True) or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = get_user_by_email(email)
    if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return jsonify({"error": "Invalid email or password"}), 401

    session["user_id"] = user["id"]
    return jsonify({"ok": True, "email": user["email"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me", methods=["GET"])
def me():
    uid = current_user_id()
    if not uid:
        return jsonify({"authenticated": False})
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT email FROM users WHERE id = %s", (uid,))
            row = cur.fetchone()
    if not row:
        session.clear()
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "email": row["email"]})


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/search", methods=["POST"])
def search():
    uid, err = require_auth()
    if err:
        return err

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

    # Return cached results if fresh enough
    cached = cache_get(filters)
    if cached is not None:
        grouped: dict[str, list] = {}
        for listing in cached:
            source = listing.get("source", "Other")
            grouped.setdefault(source, []).append(listing)
        return jsonify({"results": grouped, "total": len(cached), "cached": True})

    try:
        listings = asyncio.run(run_agent(filters, sources))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    cache_set(filters, listings)

    grouped: dict[str, list] = {}
    for listing in listings:
        source = listing.get("source", "Other")
        grouped.setdefault(source, []).append(listing)

    return jsonify({"results": grouped, "total": len(listings), "cached": False})


@app.route("/api/saved", methods=["GET"])
def get_saved():
    uid, err = require_auth()
    if err:
        return err
    return jsonify({"listings": load_saved(uid)})


@app.route("/api/save", methods=["POST"])
def save_listing():
    uid, err = require_auth()
    if err:
        return err
    listing = request.get_json(force=True)
    if not listing:
        return jsonify({"error": "No listing provided"}), 400
    save_one(uid, listing)
    return jsonify({"ok": True})


@app.route("/api/save", methods=["DELETE"])
def unsave_listing():
    uid, err = require_auth()
    if err:
        return err
    data = request.get_json(force=True) or {}
    key  = (data.get("key") or "").lower().strip()
    if not key:
        return jsonify({"error": "key required"}), 400
    delete_one(uid, key)
    return jsonify({"ok": True})


@app.route("/api/save/clear", methods=["POST"])
def clear_saved():
    uid, err = require_auth()
    if err:
        return err
    clear_all(uid)
    return jsonify({"ok": True})


@app.route("/api/pass", methods=["POST"])
def pass_listing():
    uid, err = require_auth()
    if err:
        return err
    data = request.get_json(force=True) or {}
    key  = (data.get("key") or "").lower().strip()
    if not key:
        return jsonify({"error": "key required"}), 400
    pass_one(uid, key)
    return jsonify({"ok": True})


@app.route("/api/pass", methods=["DELETE"])
def unpass_listing():
    uid, err = require_auth()
    if err:
        return err
    data = request.get_json(force=True) or {}
    key  = (data.get("key") or "").lower().strip()
    if not key:
        return jsonify({"error": "key required"}), 400
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM passed_listings WHERE user_id = %s AND key = %s", (uid, key))
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/seen", methods=["GET"])
def get_seen():
    """Returns all keys the user has already saved or passed on."""
    uid, err = require_auth()
    if err:
        return err
    saved_keys  = [listing_key(l) for l in load_saved(uid)]
    passed_keys = load_passed_keys(uid)
    return jsonify({"keys": list(set(saved_keys + passed_keys))})


@app.route("/api/passed", methods=["GET"])
def get_passed():
    uid, err = require_auth()
    if err:
        return err
    keys = load_passed_keys(uid)
    return jsonify({"keys": keys})


@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    cache_clear()
    return jsonify({"ok": True})


# ── Amenities (OpenStreetMap — free, no API key) ──────────────────────────────

_OSM_HEADERS = {"User-Agent": "Abode/1.0 (apartment search app)"}


def _osm_get(url: str) -> dict | list:
    req = urllib.request.Request(url, headers=_OSM_HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _geocode(address: str) -> tuple[float, float] | None:
    """Return (lat, lng) via Nominatim, or None on failure."""
    params = urllib.parse.urlencode({"q": address, "format": "json", "limit": 1})
    results = _osm_get(f"https://nominatim.openstreetmap.org/search?{params}")
    if not results:
        return None
    return float(results[0]["lat"]), float(results[0]["lon"])


def _haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Approximate distance in metres between two lat/lng points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return int(2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


# Overpass amenity tags to query for each category
_OVERPASS_TAGS = {
    "transit": [
        '["railway"~"subway_entrance|station|tram_stop"]',
        '["public_transport"="stop_position"]["bus"="yes"]',
    ],
    "grocery": [
        '["shop"~"supermarket|grocery|convenience"]',
    ],
    "gym": [
        '["leisure"~"fitness_centre|sports_centre"]',
        '["amenity"="gym"]',
    ],
}


def _overpass_nearby(lat: float, lng: float, category: str, radius: int = 1200) -> list[dict]:
    """Query Overpass API for nearby OSM nodes/ways and return up to 3 results."""
    tag_filters = _OVERPASS_TAGS.get(category, [])
    # Build a union of node queries for each tag filter
    union_parts = []
    for tag in tag_filters:
        union_parts.append(f'node{tag}(around:{radius},{lat},{lng});')
    query = f"[out:json][timeout:8];({' '.join(union_parts)});out body 10;"
    params = urllib.parse.urlencode({"data": query})
    data = _osm_get(f"https://overpass-api.de/api/interpreter?{params}")

    seen_names: set[str] = set()
    out = []
    for el in (data.get("elements") or []):
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("ref") or ""
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        dist = _haversine_meters(lat, lng, el["lat"], el["lon"])
        out.append({"name": name, "distance_m": dist})
        if len(out) == 3:
            break

    out.sort(key=lambda x: x["distance_m"])
    return out


@app.route("/api/amenities", methods=["GET"])
def get_amenities():
    uid, err = require_auth()
    if err:
        return err

    address = (request.args.get("address") or "").strip()
    if not address:
        return jsonify({"error": "address param required"}), 400

    try:
        coords = _geocode(address)
        if not coords:
            return jsonify({"error": "Could not geocode address"}), 404
        lat, lng = coords

        transit = _overpass_nearby(lat, lng, "transit")
        grocery = _overpass_nearby(lat, lng, "grocery")
        gym     = _overpass_nearby(lat, lng, "gym")
        return jsonify({"transit": transit, "grocery": grocery, "gym": gym})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if DATABASE_URL:
        init_db()
    print(f"Abode UI → http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT)


# Called by gunicorn — init DB on startup
if DATABASE_URL:
    init_db()
