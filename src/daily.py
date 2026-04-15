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


def send_email(new_2by2: list, new_1by1: list):
    """Send email with new listings to neilg2001@gmail.com"""
    sender_email = os.getenv("GMAIL_ADDRESS")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient_email = "neilg2001@gmail.com"

    if not sender_email or not sender_password:
        print("Warning: Email credentials not configured (GMAIL_ADDRESS, GMAIL_APP_PASSWORD)")
        return

    total = len(new_2by2) + len(new_1by1)

    # Build email body
    if total == 0:
        body = "No new listings found today."
        subject = "Apartment Finder - No new listings"
    else:
        body = "New apartment listings found:\n\n"
        body += format_section("2 Bed / 2 Bath", new_2by2)
        body += "\n"
        body += format_section("1 Bed / 1 Bath", new_1by1)
        subject = f"Apartment Finder - {total} new listings"

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
    new_2by2, new_1by1 = await run_daily_agent()
    send_email(new_2by2, new_1by1)


if __name__ == "__main__":
    asyncio.run(main())
