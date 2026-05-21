import asyncio
import hashlib
import json
import math
import os
import secrets
import urllib.error
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
from scrapers.zillow import NEIGHBORHOOD_BOUNDS

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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_prefs (
                    user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    prefs       JSONB NOT NULL,
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS agent_listings (
                    id          SERIAL PRIMARY KEY,
                    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    key         TEXT NOT NULL,
                    data        JSONB NOT NULL,
                    category    TEXT NOT NULL DEFAULT '',
                    found_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (user_id, key)
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


# ── User prefs helpers ────────────────────────────────────────────────────────

def load_prefs(user_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT prefs FROM user_prefs WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
    return dict(row["prefs"]) if row else None


def save_prefs(user_id: int, prefs: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_prefs (user_id, prefs, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (user_id) DO UPDATE
                    SET prefs      = EXCLUDED.prefs,
                        updated_at = EXCLUDED.updated_at
            """, (user_id, json.dumps(prefs)))
        conn.commit()


def load_all_user_prefs() -> list[dict]:
    """Return all users' prefs — used by the daily job."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT user_id, prefs FROM user_prefs")
            return [{"user_id": row["user_id"], "prefs": dict(row["prefs"])} for row in cur.fetchall()]


# ── Agent listings helpers ────────────────────────────────────────────────────

def save_agent_listings(user_id: int, listings: list[dict], category: str) -> None:
    """Upsert listings found by the daily job for a specific user."""
    if not DATABASE_URL or not listings:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            for listing in listings:
                key = listing_key(listing)
                if not key:
                    continue
                cur.execute("""
                    INSERT INTO agent_listings (user_id, key, data, category, found_at)
                    VALUES (%s, %s, %s, %s, now())
                    ON CONFLICT (user_id, key) DO UPDATE
                        SET data     = EXCLUDED.data,
                            category = EXCLUDED.category,
                            found_at = EXCLUDED.found_at
                """, (user_id, key, json.dumps(listing), category))
        conn.commit()


def purge_expired_agent_listings(user_id: int, active_keys: set) -> int:
    """Delete agent listings no longer present in the latest scrape results."""
    if not DATABASE_URL or not active_keys:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key FROM agent_listings WHERE user_id = %s", (user_id,))
            stored_keys = {row[0] for row in cur.fetchall()}
        expired_keys = list(stored_keys - active_keys)
        if not expired_keys:
            return 0
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM agent_listings WHERE user_id = %s AND key = ANY(%s)",
                (user_id, expired_keys),
            )
        conn.commit()
    return len(expired_keys)


def load_agent_listings(user_id: int) -> list[dict]:
    """Return agent listings for a user, newest first."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT data, category, found_at
                FROM agent_listings
                WHERE user_id = %s
                ORDER BY found_at DESC
            """, (user_id,))
            rows = cur.fetchall()
    result = []
    for row in rows:
        listing = dict(row["data"])
        listing["_category"] = row["category"]
        listing["_found_at"] = row["found_at"].isoformat()
        result.append(listing)
    return result


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

    sources      = ["zillow"]
    bedrooms     = data.get("bedrooms")
    min_baths    = data.get("minBaths")
    max_rent     = data.get("maxRent")
    min_rent     = data.get("minRent", 0)
    min_sqft     = data.get("minSqft")
    laundry      = bool(data.get("laundry", False))
    parking      = bool(data.get("parking", False))
    neighborhoods = data.get("neighborhoods", ["lincoln_park"])
    if isinstance(neighborhoods, str):
        neighborhoods = [neighborhoods]

    if not max_rent or not bedrooms:
        return jsonify({"error": "bedrooms and maxRent are required"}), 400

    filters = {
        "maxRent":        int(max_rent),
        "minRent":        int(min_rent),
        "bedrooms":       int(bedrooms),
        "minBaths":       int(min_baths) if min_baths else None,
        "minSqft":        int(min_sqft) if min_sqft else None,
        "laundry":        laundry,
        "parking":        parking,
        "neighborhoods":  neighborhoods,
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
        listings, scraper_errors = asyncio.run(run_agent(filters, sources))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if listings:
        cache_set(filters, listings)

    grouped: dict[str, list] = {}
    for listing in listings:
        source = listing.get("source", "Other")
        grouped.setdefault(source, []).append(listing)

    resp: dict = {"results": grouped, "total": len(listings), "cached": False}
    if scraper_errors:
        resp["errors"] = scraper_errors
    return jsonify(resp)


INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")


@app.route("/api/internal/search", methods=["POST"])
def internal_search():
    """Scrape endpoint for the daily cron job — authenticated by shared secret, not session."""
    secret = request.headers.get("X-Internal-Secret", "")
    if not INTERNAL_SECRET or secret != INTERNAL_SECRET:
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json(force=True) or {}
    bedrooms      = data.get("bedrooms")
    min_baths     = data.get("minBaths")
    max_rent      = data.get("maxRent")
    min_rent      = data.get("minRent", 0)
    min_sqft      = data.get("minSqft")
    laundry       = bool(data.get("laundry", False))
    parking       = bool(data.get("parking", False))
    neighborhoods = data.get("neighborhoods", ["lincoln_park"])
    if isinstance(neighborhoods, str):
        neighborhoods = [neighborhoods]

    if not max_rent or not bedrooms:
        return jsonify({"error": "bedrooms and maxRent are required"}), 400

    filters = {
        "maxRent":       int(max_rent),
        "minRent":       int(min_rent),
        "bedrooms":      int(bedrooms),
        "minBaths":      int(min_baths) if min_baths else None,
        "minSqft":       int(min_sqft) if min_sqft else None,
        "laundry":       laundry,
        "parking":       parking,
        "neighborhoods": neighborhoods,
    }

    # Use cache if available — avoids redundant scrapes if cron runs close to a user search
    cached = cache_get(filters)
    if cached is not None:
        return jsonify({"listings": cached, "cached": True})

    try:
        listings, _ = asyncio.run(run_agent(filters, ["zillow"]))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if listings:
        cache_set(filters, listings)

    return jsonify({"listings": listings, "cached": False})


@app.route("/api/internal/send-email", methods=["POST"])
def internal_send_email():
    """Send email on behalf of the cron job via Resend API (HTTPS, never blocked)."""
    secret = request.headers.get("X-Internal-Secret", "")
    if not INTERNAL_SECRET or secret != INTERNAL_SECRET:
        return jsonify({"error": "Forbidden"}), 403

    data    = request.get_json(force=True) or {}
    to_addr = data.get("to")
    subject = data.get("subject")
    body    = data.get("body")

    if not all([to_addr, subject, body]):
        return jsonify({"error": "to, subject, and body are required"}), 400

    resend_api_key = os.getenv("RESEND_API_KEY")
    resend_from    = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")

    if not resend_api_key:
        return jsonify({"error": "RESEND_API_KEY not configured"}), 500

    payload = json.dumps({
        "from":    resend_from,
        "to":      [to_addr],
        "subject": subject,
        "text":    body,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {resend_api_key}",
            "Content-Type":  "application/json",
            "User-Agent":    "python-requests/2.31.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        return jsonify({"ok": True})
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"  Resend API error: HTTP {e.code} — {err_body}")
        return jsonify({"error": f"Resend error {e.code}: {err_body}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


@app.route("/api/prefs", methods=["GET"])
def get_prefs():
    uid, err = require_auth()
    if err:
        return err
    prefs = load_prefs(uid)
    return jsonify({"prefs": prefs})


@app.route("/api/prefs", methods=["POST"])
def post_prefs():
    uid, err = require_auth()
    if err:
        return err
    prefs = request.get_json(force=True)
    if not prefs or not isinstance(prefs, dict):
        return jsonify({"error": "Invalid prefs"}), 400
    save_prefs(uid, prefs)
    return jsonify({"ok": True})


@app.route("/api/agent/listings", methods=["GET"])
def get_agent_listings():
    uid, err = require_auth()
    if err:
        return err
    listings = load_agent_listings(uid)
    return jsonify({"listings": listings})


@app.route("/api/agent/listings", methods=["DELETE"])
def delete_agent_listing():
    uid, err = require_auth()
    if err:
        return err
    data = request.get_json(force=True) or {}
    key  = (data.get("key") or "").lower().strip()
    if not key:
        return jsonify({"error": "key required"}), 400
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM agent_listings WHERE user_id = %s AND key = %s",
                (uid, key),
            )
        conn.commit()
    # Also add to passed so the daily job won't re-add it
    pass_one(uid, key)
    return jsonify({"ok": True})


@app.route("/api/neighborhoods", methods=["GET"])
def get_neighborhoods():
    labels = {
        "all":           "All Chicago",
        "lincoln_park":  "Lincoln Park",
        "wicker_park":   "Wicker Park",
        "river_north":   "River North",
        "west_loop":     "West Loop",
        "logan_square":  "Logan Square",
        "lakeview":      "Lakeview",
        "streeterville": "Streeterville",
        "south_loop":    "South Loop",
        "bucktown":      "Bucktown",
        "old_town":      "Old Town",
        "andersonville": "Andersonville",
    }
    return jsonify([{"key": k, "label": labels.get(k, k)} for k in NEIGHBORHOOD_BOUNDS])


@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    cache_clear()
    return jsonify({"ok": True})


@app.route("/api/photos", methods=["GET"])
def get_photos():
    """Scrape all listing photos from a Zillow detail page URL."""
    uid, err = require_auth()
    if err:
        return err

    listing_url = (request.args.get("url") or "").strip()
    if not listing_url or "zillow.com" not in listing_url:
        return jsonify({"photos": []})

    import re as _re
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    }
    import ssl as _ssl
    ssl_ctx = _ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = _ssl.CERT_NONE

    try:
        req = urllib.request.Request(listing_url, headers=headers)
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return jsonify({"photos": [], "error": str(e)})

    # Zillow embeds photo URLs in a JSON blob — grab all hdImageUrl / url values
    photos = []
    seen = set()

    # Pattern 1: "hdImageUrl":"https://..."
    for m in _re.finditer(r'"hdImageUrl"\s*:\s*"([^"]+)"', html):
        url = m.group(1)
        if url not in seen:
            seen.add(url)
            photos.append(url)

    # Pattern 2: "url":"https://photos.zillowstatic.com/..."
    if not photos:
        for m in _re.finditer(r'"url"\s*:\s*"(https://photos\.zillowstatic\.com[^"]+)"', html):
            url = m.group(1)
            if url not in seen:
                seen.add(url)
                photos.append(url)

    return jsonify({"photos": photos})


@app.route("/api/lookup", methods=["GET"])
def lookup_address():
    """Geocode an address then do a tight Zillow search to find a matching listing."""
    uid, err = require_auth()
    if err:
        return err

    address = (request.args.get("address") or "").strip()
    if not address:
        return jsonify({"error": "address param required"}), 400

    # Geocode to get lat/lng
    if "chicago" not in address.lower():
        address_hint = address + ", Chicago, IL"
    else:
        address_hint = address
    coords = _geocode(address_hint)
    if not coords:
        return jsonify({"listing": None})

    lat, lng = coords
    # Build a tight ~400m bounding box around the geocoded point
    delta = 0.003  # ~330m
    map_bounds = {
        "west":  lng - delta,
        "east":  lng + delta,
        "south": lat - delta,
        "north": lat + delta,
    }

    import asyncio as _asyncio
    from scrapers.zillow import build_payload, ZILLOW_API_URL
    import ssl as _ssl, json as _json, urllib.request as _urlreq

    payload = build_payload(max_rent=999999, min_rent=0, map_bounds=map_bounds)
    body = _json.dumps(payload).encode("utf-8")
    req = _urlreq.Request(
        ZILLOW_API_URL, data=body, method="PUT",
        headers={
            "accept": "*/*", "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json", "content-length": str(len(body)),
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        },
    )
    ssl_ctx = _ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = _ssl.CERT_NONE

    try:
        with _urlreq.urlopen(req, context=ssl_ctx) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return jsonify({"listing": None})

    import re as _re
    from datetime import datetime as _dt, timezone as _tz
    results = (data.get("cat1") or {}).get("searchResults", {}).get("mapResults", [])
    best = None
    q_lower = address.lower()
    for r in results:
        addr = (r.get("address") or "").lower()
        # Prefer exact street number match
        if q_lower.split()[0] in addr:
            best = r
            break
    if not best and results:
        best = results[0]

    if not best:
        return jsonify({"listing": None})

    price_raw = best.get("price") or best.get("unformattedPrice") or ""
    numeric_price = _re.sub(r"\D", "", str(price_raw))
    listing = {
        "title":     best.get("address", address),
        "price":     f"${numeric_price}/mo" if numeric_price else "—",
        "location":  best.get("address", address),
        "url":       best.get('detailUrl', '') if best.get('detailUrl', '').startswith('http') else f"https://www.zillow.com{best.get('detailUrl', '')}",
        "beds":      best.get("minBeds", ""),
        "baths":     best.get("minBaths", ""),
        "sqft":      best.get("minArea", ""),
        "image":     best.get("imgSrc", ""),
        "source":    "Zillow",
        "scrapedAt": _dt.now(_tz.utc).isoformat(),
    }
    lat2 = (best.get("latLong") or {}).get("latitude")
    lng2 = (best.get("latLong") or {}).get("longitude")
    if lat2 and lng2:
        listing["lat"] = lat2
        listing["lng"] = lng2
    return jsonify({"listing": listing})


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


def _overpass_all(lat: float, lng: float, radius: int = 1200) -> dict:
    """Single Overpass query fetching transit, grocery, and gym nodes together."""
    around = f"around:{radius},{lat},{lng}"
    query = f"""
[out:json][timeout:20];
(
  node["railway"~"subway_entrance|station|tram_stop"]({around});
  node["public_transport"="stop_position"]["bus"="yes"]({around});
  node["shop"~"supermarket|grocery|convenience"]({around});
  node["leisure"~"fitness_centre|sports_centre"]({around});
  node["amenity"="gym"]({around});
);
out body 60;
"""
    params = urllib.parse.urlencode({"data": query})
    data = _osm_get(f"https://overpass-api.de/api/interpreter?{params}")

    def _category(tags: dict) -> str | None:
        railway = tags.get("railway", "")
        pt      = tags.get("public_transport", "")
        shop    = tags.get("shop", "")
        leisure = tags.get("leisure", "")
        amenity = tags.get("amenity", "")
        if railway in ("subway_entrance", "station", "tram_stop") or (pt == "stop_position" and tags.get("bus") == "yes"):
            return "transit"
        if shop in ("supermarket", "grocery", "convenience"):
            return "grocery"
        if leisure in ("fitness_centre", "sports_centre") or amenity == "gym":
            return "gym"
        return None

    buckets: dict[str, list] = {"transit": [], "grocery": [], "gym": []}
    seen: dict[str, set] = {"transit": set(), "grocery": set(), "gym": set()}

    for el in (data.get("elements") or []):
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("ref") or ""
        if not name:
            continue
        cat = _category(tags)
        if not cat or name in seen[cat] or len(buckets[cat]) >= 3:
            continue
        seen[cat].add(name)
        elat, elng = el["lat"], el["lon"]
        dist = _haversine_meters(lat, lng, elat, elng)
        maps_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(name)}&center={elat},{elng}"
        buckets[cat].append({"name": name, "distance_m": dist, "url": maps_url})

    for cat in buckets:
        buckets[cat].sort(key=lambda x: x["distance_m"])

    return buckets


@app.route("/api/amenities", methods=["GET"])
def get_amenities():
    uid, err = require_auth()
    if err:
        return err

    try:
        # Use pre-scraped coords if provided (avoids geocoding entirely)
        raw_lat = request.args.get("lat")
        raw_lng = request.args.get("lng")
        if raw_lat and raw_lng:
            lat, lng = float(raw_lat), float(raw_lng)
        else:
            address = (request.args.get("address") or "").strip()
            if not address:
                return jsonify({"error": "lat/lng or address param required"}), 400
            # Append city hint if not already present so Nominatim resolves correctly
            if "chicago" not in address.lower():
                address = address + ", Chicago, IL"
            coords = _geocode(address)
            if not coords:
                return jsonify({"error": "Could not geocode address"}), 404
            lat, lng = coords

        buckets = _overpass_all(lat, lng)
        return jsonify({"transit": buckets["transit"], "grocery": buckets["grocery"], "gym": buckets["gym"]})
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
