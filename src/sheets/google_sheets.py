import json
import os

import httplib2
import google_auth_httplib2
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

HEADERS = [
    "Address", "URL", "Rent", "Sqft", "Source",
]

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_service():
    credentials_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
    credentials_info = json.loads(credentials_json)
    creds = Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
    http = httplib2.Http(disable_ssl_certificate_validation=True)
    authorized_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)
    return build("sheets", "v4", http=authorized_http)


def listing_to_row(listing: dict) -> list:
    return [
        listing.get("location", ""),
        listing.get("url", ""),
        listing.get("price", ""),
        listing.get("sqft", ""),
        listing.get("source", ""),
    ]


async def sync_to_sheets(listings: list[dict], sheet_key: str = "2by2") -> None:
    service = get_service()
    spreadsheet_id = config.sheets["spreadsheetId"]
    sheet_name = config.sheets[sheet_key]

    # Get spreadsheet metadata
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_titles = [s["properties"]["title"] for s in meta.get("sheets", [])]

    # Create sheet if it doesn't exist
    if sheet_name not in sheet_titles:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
        ).execute()
        # Refresh metadata
        meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()

    # Always update headers
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="RAW",
        body={"values": [HEADERS]},
    ).execute()

    # Get existing listings
    existing_data = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!B:B",
    ).execute()
    existing_urls = set()
    if "values" in existing_data and len(existing_data["values"]) > 1:
        # Skip header row (index 0)
        existing_urls = {row[0].lower().strip() for row in existing_data["values"][1:] if row}

    # Filter to only new listings
    new_listings = [l for l in listings if l.get("url", "").lower().strip() not in existing_urls]

    # Append new listings
    if new_listings:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A2",
            valueInputOption="RAW",
            body={"values": [listing_to_row(l) for l in new_listings]},
        ).execute()
        print(f"\nAdded {len(new_listings)} new listings → https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
    else:
        print(f"\nNo new listings to add → https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
