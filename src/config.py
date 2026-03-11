import os

search = {
    "city": "Chicago, IL",
    "maxRent": 2000,
    "bedrooms": 2,
}

preferred_neighborhoods = [
    "Wicker Park",
    "Logan Square",
    "Lincoln Park",
    "Lakeview",
    "West Loop",
]

bonus_keywords = [
    "hardwood floors",
    "in-unit laundry",
    "dishwasher",
    "central air",
    "roof deck",
    "parking",
    "pet friendly",
    "no fee",
]

red_flag_keywords = [
    "no pets",
    "utilities not included",
    "income verification",
    "guarantor required",
]

sheets = {
    "spreadsheetId": os.environ.get("GOOGLE_SHEET_ID", ""),
    "sheetName": "Listings",
}

schedule = "0 21 * * *"
