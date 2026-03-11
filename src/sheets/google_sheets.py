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
    "Score", "Title", "Price", "Location", "Beds", "Baths", "Sqft",
    "Summary", "Bonus Flags", "Red Flags", "Neighborhood Match",
    "Within Budget", "Source", "URL", "Scraped At",
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
        listing.get("score", ""),
        listing.get("title", ""),
        listing.get("price", ""),
        listing.get("location", ""),
        listing.get("beds", ""),
        listing.get("baths", ""),
        listing.get("sqft", ""),
        listing.get("summary", ""),
        ", ".join(listing.get("bonusFlags") or []),
        ", ".join(listing.get("redFlags") or []),
        "✅" if listing.get("neighborhoodMatch") else "❌",
        "✅" if listing.get("withinBudget") else "❌",
        listing.get("source", ""),
        listing.get("url", ""),
        listing.get("scrapedAt", ""),
    ]


async def sync_to_sheets(listings: list[dict]) -> None:
    service = get_service()
    spreadsheet_id = config.sheets["spreadsheetId"]
    sheet_name = config.sheets["sheetName"]

    # Get spreadsheet metadata
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_titles = [s["properties"]["title"] for s in meta.get("sheets", [])]

    # Create sheet if it doesn't exist
    if sheet_name not in sheet_titles:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
        ).execute()
        # Add headers
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        ).execute()
        # Refresh metadata
        meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()

    # Clear existing data rows
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A2:Z10000",
    ).execute()

    # Write new listings
    if listings:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A2",
            valueInputOption="RAW",
            body={"values": [listing_to_row(l) for l in listings]},
        ).execute()

    # Highlight top 3 listings in green
    top_count = min(3, len(listings))
    if top_count > 0:
        sheet_id = next(
            (s["properties"]["sheetId"] for s in meta.get("sheets", []) if s["properties"]["title"] == sheet_name),
            0,
        )
        requests = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": i + 1,
                        "endRowIndex": i + 2,
                        "startColumnIndex": 0,
                        "endColumnIndex": len(HEADERS),
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.85, "green": 0.96, "blue": 0.85}
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
            for i in range(top_count)
        ]
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()

    print(f"\nSynced {len(listings)} listings → https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
