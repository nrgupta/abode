import asyncio
import os
import smtplib
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.listingsTool import run_daily_agent
from sheets.google_sheets import sync_to_sheets


def send_email(listings):
    """Send email with new listings to neilg2001@gmail.com"""
    sender_email = os.getenv("GMAIL_ADDRESS")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient_email = "neilg2001@gmail.com"

    if not sender_email or not sender_password:
        print("Warning: Email credentials not configured (GMAIL_ADDRESS, GMAIL_APP_PASSWORD)")
        return

    # Build email body
    if not listings:
        body = "No listings found today."
        subject = "Apartment Finder - No listings found"
    else:
        body = "New apartment listings found:\n\n"

        by_source: dict[str, list] = {}
        for listing in listings:
            by_source.setdefault(listing.get("source", "Unknown"), []).append(listing)

        for source, source_listings in by_source.items():
            body += f"\n{source} ({len(source_listings)} listings):\n"
            body += "-" * 50 + "\n"
            for listing in source_listings:
                body += f"\n{listing.get('title', 'N/A')}\n"
                body += f"Price: {listing.get('price', 'N/A')} | Location: {listing.get('location', 'N/A')}\n"
                if listing.get("beds"):
                    body += f"Beds: {listing['beds']} | Baths: {listing.get('baths', 'N/A')} | Sqft: {listing.get('sqft', 'N/A')}\n"
                body += f"URL: {listing.get('url', 'N/A')}\n"

        subject = f"Apartment Finder - {len(listings)} new listings"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = recipient_email
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, msg.as_string())

        print(f"Email sent to {recipient_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")


async def main():
    print("Running daily apartment search...")
    listings = await run_daily_agent()

    if listings:
        await sync_to_sheets(listings)

    send_email(listings)


if __name__ == "__main__":
    asyncio.run(main())
