module.exports = {
  search: {
    city: "Chicago, IL",
    maxRent: 2000,
    bedrooms: 2,
  },
  preferredNeighborhoods: [
    "Wicker Park",
    "Logan Square",
    "Lincoln Park",
    "Lakeview",
    "West Loop",
  ],
  bonusKeywords: [
    "hardwood floors",
    "in-unit laundry",
    "dishwasher",
    "central air",
    "roof deck",
    "parking",
    "pet friendly",
    "no fee",
  ],
  redFlagKeywords: [
    "no pets",
    "utilities not included",
    "income verification",
    "guarantor required",
  ],
  sheets: {
    spreadsheetId: process.env.GOOGLE_SHEET_ID,
    sheetName: "Listings",
  },
  schedule: "0 21 * * *",
};
