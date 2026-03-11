import os

search = {
    "city": "Chicago, IL",
    "max_price": 4200,
    "min_bedrooms": 2,
    "max_bedrooms": 2,
    "min_bathrooms": 2,
    "max_bathrooms": 2,
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
