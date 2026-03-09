const { google } = require("googleapis");
const config = require("../config");

const HEADERS = ["Score","Title","Price","Location","Beds","Baths","Sqft","Summary","Bonus Flags","Red Flags","Neighborhood Match","Within Budget","Source","URL","Scraped At"];

function getAuth() {
  const credentials = JSON.parse(process.env.GOOGLE_SERVICE_ACCOUNT_JSON);
  return new google.auth.GoogleAuth({ credentials, scopes: ["https://www.googleapis.com/auth/spreadsheets"] });
}

function listingToRow(l) {
  return [l.score??"",l.title??"",l.price??"",l.location??"",l.beds??"",l.baths??"",l.sqft??"",l.summary??"",(l.bonusFlags||[]).join(", "),(l.redFlags||[]).join(", "),l.neighborhoodMatch?"✅":"❌",l.withinBudget?"✅":"❌",l.source??"",l.url??"",l.scrapedAt??""];
}

async function syncToSheets(listings) {
  const auth = getAuth();
  const sheets = google.sheets({ version: "v4", auth });
  const { spreadsheetId, sheetName } = config.sheets;
  const meta = await sheets.spreadsheets.get({ spreadsheetId });
  const sheetExists = meta.data.sheets.some(s => s.properties.title === sheetName);
  if (!sheetExists) {
    await sheets.spreadsheets.batchUpdate({ spreadsheetId, requestBody: { requests: [{ addSheet: { properties: { title: sheetName } } }] } });
    await sheets.spreadsheets.values.update({ spreadsheetId, range: `${sheetName}!A1`, valueInputOption: "RAW", requestBody: { values: [HEADERS] } });
  }
  await sheets.spreadsheets.values.clear({ spreadsheetId, range: `${sheetName}!A2:Z10000` });
  await sheets.spreadsheets.values.update({ spreadsheetId, range: `${sheetName}!A2`, valueInputOption: "RAW", requestBody: { values: listings.map(listingToRow) } });
  const topCount = Math.min(3, listings.length);
  if (topCount > 0) {
    const sheetId = meta.data.sheets.find(s => s.properties.title === sheetName)?.properties?.sheetId ?? 0;
    await sheets.spreadsheets.batchUpdate({ spreadsheetId, requestBody: { requests: Array.from({ length: topCount }, (_, i) => ({ repeatCell: { range: { sheetId, startRowIndex: i+1, endRowIndex: i+2, startColumnIndex: 0, endColumnIndex: HEADERS.length }, cell: { userEnteredFormat: { backgroundColor: { red: 0.85, green: 0.96, blue: 0.85 } } }, fields: "userEnteredFormat.backgroundColor" } })) } });
  }
  console.log(`\n✅ Synced ${listings.length} listings → https://docs.google.com/spreadsheets/d/${spreadsheetId}`);
}

module.exports = { syncToSheets };
