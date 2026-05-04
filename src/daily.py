import asyncio
import os
import smtplib
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.listingsTool import run_agent
from server import load_all_user_prefs, save_agent_listings
from sheets.google_sheets import sync_to_sheets
from server import save_agent_listings


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


def send_email(new_listings: list, _unused: list, user_id: int | None = None):
    """Send email digest of new listings to the user."""
    sender_email    = os.getenv("GMAIL_ADDRESS")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")

    if not sender_email or not sender_password:
        print("Warning: Email credentials not configured (GMAIL_ADDRESS, GMAIL_APP_PASSWORD)")
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

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, msg.as_string())

        print(f"  Email sent to {recipient_email}")
    except Exception as e:
        print(f"  Failed to send email: {e}")


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
    listings = await run_agent(filters, sources=["zillow"])
    new_listings = await sync_to_sheets(listings, sheet_key=f"user_{user_id}")
    save_agent_listings(user_id, new_listings, category)
    print(f"  User {user_id}: {len(new_listings)} new listings saved")
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
                send_email(new_listings, [], user_id)
            else:
                print(f"  User {user_id}: email notifications off, skipping email")
        except Exception as e:
            print(f"  User {user_id}: error — {e}")


if __name__ == "__main__":
    asyncio.run(main())
