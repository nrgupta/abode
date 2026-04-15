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

    # Get sheet id for clear operation
    sheet_id = next(
        s["properties"]["sheetId"]
        for s in meta.get("sheets", [])
        if s["properties"]["title"] == sheet_name
    )

    # Clear all existing data
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"updateCells": {"range": {"sheetId": sheet_id}, "fields": "userEnteredValue"}}]},
    ).execute()

    # Write headers and all listings
    rows = [HEADERS] + [listing_to_row(l) for l in listings]
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="RAW",
        body={"values": rows},
    ).execute()
    print(f"\nWrote {len(listings)} listings → https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
