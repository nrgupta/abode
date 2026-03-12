import os

search2by2 = {
    "city": "Chicago, IL",
    "maxRent": 4200,
    "bedrooms": 2,
    "maxBedrooms": 2,
    "minBaths": 2,
    "maxBaths": 2,
    "minSqft": 900,
}

search1by1 = {
    "city": "Chicago, IL",
    "maxRent": 2200,
    "bedrooms": 1,
    "maxBedrooms": 1,
    "minBaths": 1,
    "maxBaths": 1,
    "minSqft": 500,
}

# Default search configuration
search = search2by2

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
    "2by2": "2by2",
    "1by1": "1by1",
}

schedule = "30 20 * * *"
