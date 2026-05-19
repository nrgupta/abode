import asyncio
import json
import os
import smtplib
import sys
import urllib.request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import (
    load_all_user_prefs, save_agent_listings, purge_expired_agent_listings,
    load_saved, load_passed_keys, load_agent_listings, listing_key,
)

# If set, delegate Zillow scraping to the web service (avoids cron IP blocks)
WEB_SERVICE_URL = os.environ.get("WEB_SERVICE_URL", "").rstrip("/")
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")


def format_section(title: str, listings: list) -> str:
    section = f"{title} ({len(listings)} new):\n"
    section += "=" * 50 + "\n"
    if not listings:
        section += "No new listings.\n"
    else:
        for listing in listings:
            section += f"\n{listing.get('title', 'N/A')}\n"
            section += f"Price: {listing.get('price', 'N/A')} | Location: {listing.get('location', 'N/A')}\n"
            if listing.get("beds"):
                section += f"Beds: {listing['beds']} | Baths: {listing.get('baths', 'N/A')} | Sqft: {listing.get('sqft', 'N/A')}\n"
            section += f"URL: {listing.get('url', 'N/A')}\n"
    return section


def get_user_email(user_id: int) -> str | None:
    """Look up a user's email from the DB."""
    from server import get_conn
    import psycopg2.extras
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT email FROM users WHERE id = %s", (user_id,))
                row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def send_email(new_listings: list, _unused: list, user_id: int | None = None, gmail_address: str | None = None, gmail_app_password: str | None = None):
    """Send email digest of new listings to the user."""
    # Prefer per-user credentials from prefs; fall back to env vars
    sender_email    = gmail_address    or os.getenv("GMAIL_ADDRESS")
    sender_password = gmail_app_password or os.getenv("GMAIL_APP_PASSWORD")

    if not sender_email or not sender_password:
        print("Warning: Email credentials not configured (set Gmail address/app password in Profile)")
        return

    recipient_email = get_user_email(user_id) if user_id else "neilg2001@gmail.com"
    if not recipient_email:
        print(f"  User {user_id}: could not find email address, skipping notification")
        return

    total = len(new_listings)

    if total == 0:
        body    = "No new listings found today."
        subject = "Abode - No new listings today"
    else:
        body    = "New apartment listings found:\n\n"
        body   += format_section("New Listings", new_listings)
        subject = f"Abode - {total} new listing{'s' if total != 1 else ''} found"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = sender_email
        msg["To"]      = recipient_email
        msg.attach(MIMEText(body, "plain"))

        print(f"  Connecting to smtp.gmail.com:465...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            print(f"  Logging in as {sender_email}...")
            server.login(sender_email, sender_password)
            print(f"  Sending email...")
            server.sendmail(sender_email, recipient_email, msg.as_string())

        print(f"  Email sent to {recipient_email}")
    except Exception as e:
        print(f"  Failed to send email: {e}")


async def _scrape_listings(filters: dict) -> list[dict]:
    """Fetch listings via the web service (preferred) or directly as fallback."""
    if WEB_SERVICE_URL and INTERNAL_SECRET:
        url  = f"{WEB_SERVICE_URL}/api/internal/search"
        body = json.dumps(filters).encode("utf-8")
        req  = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type":      "application/json",
                "X-Internal-Secret": INTERNAL_SECRET,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            listings = data.get("listings", [])
            source   = "cache" if data.get("cached") else "web service"
            print(f"    Fetched {len(listings)} listings from {source}")
            return listings
        except Exception as e:
            print(f"    Web service scrape failed ({e}), falling back to direct scrape")

    # Direct scrape fallback (may hit IP blocks on Railway cron)
    from agent.listingsTool import run_agent
    listings, _ = await run_agent(filters, sources=["zillow"])
    return listings


async def run_for_user(user_id: int, prefs: dict) -> list[dict]:
    """Run a scrape for a single user based on their saved prefs."""
    filters = {
        "maxRent":       int(prefs.get("maxRent") or 0),
        "minRent":       0,
        "bedrooms":      int(prefs.get("bedrooms") or 1),
        "minBaths":      int(prefs.get("minBaths") or 1),
        "minSqft":       int(prefs.get("minSqft")) if prefs.get("minSqft") else None,
        "laundry":       bool(prefs.get("laundry", False)),
        "parking":       bool(prefs.get("parking", False)),
        "neighborhoods": prefs.get("neighborhoods") or ["lincoln_park"],
    }
    if not filters["maxRent"]:
        print(f"  User {user_id}: skipping — no maxRent set")
        return []

    beds = filters["bedrooms"]
    category = f"{beds}bd/{filters['minBaths']}ba"
    print(f"  User {user_id}: scraping {category}, maxRent=${filters['maxRent']}")
    listings = await _scrape_listings(filters)
    print(f"  User {user_id}: scraped {len(listings)} listings")

    # Build a set of keys the user has already acted on (saved or passed)
    saved_keys  = {listing_key(l) for l in load_saved(user_id)}
    passed_keys = set(load_passed_keys(user_id))
    seen_keys   = saved_keys | passed_keys

    # Build a set of keys already in the agent tab (so we can identify truly new ones)
    existing_agent_keys = {listing_key(l) for l in load_agent_listings(user_id)}

    # Purge agent listings no longer in the current scrape (rented/expired)
    active_keys = {listing_key(l) for l in listings}
    expired = purge_expired_agent_listings(user_id, active_keys)
    if expired:
        print(f"  User {user_id}: removed {expired} expired listing(s)")

    # Only save listings that aren't in saved or passed tabs
    eligible = [l for l in listings if listing_key(l) not in seen_keys]
    if eligible:
        save_agent_listings(user_id, eligible, category)
    print(f"  User {user_id}: {len(eligible)}/{len(listings)} eligible listings saved to agent tab")

    # New listings = eligible ones that weren't already in the agent tab
    new_listings = [l for l in eligible if listing_key(l) not in existing_agent_keys]
    print(f"  User {user_id}: {len(new_listings)} truly new listing(s) for email")

    return new_listings


async def main():
    print("Running daily apartment search...")
    all_user_prefs = load_all_user_prefs()

    if not all_user_prefs:
        print("No users with saved prefs — nothing to do.")
        return

    for entry in all_user_prefs:
        user_id = entry["user_id"]
        prefs   = entry["prefs"]
        try:
            new_listings = await run_for_user(user_id, prefs)
            if prefs.get("emailNotify"):
                has_creds = bool(prefs.get("gmailAddress") and prefs.get("gmailAppPassword"))
                print(f"  User {user_id}: email notify on, credentials {'found' if has_creds else 'MISSING'}, {len(new_listings)} new listing(s) to send")
                send_email(
                    new_listings, [], user_id,
                    gmail_address=prefs.get("gmailAddress"),
                    gmail_app_password=prefs.get("gmailAppPassword"),
                )
            else:
                print(f"  User {user_id}: email notifications off, skipping email")
        except Exception as e:
            print(f"  User {user_id}: error — {e}")


if __name__ == "__main__":
    asyncio.run(main())
