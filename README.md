# Chicago Apartment Finder

Scrapes Zillow, Redfin (Lincoln Park), and Craigslist for Chicago rentals. Includes a local web UI for searching with filters, and runs automatically every day at 3:00 PM CST via GitHub Actions.

## Sources
- **Zillow** — API-based, Chicago-wide
- **Redfin** — Lincoln Park neighborhood
- **Craigslist** — Chicago-wide, browser scrape

## Quick Start

```bash
npm install
cp .env.example .env   # fill in your API keys
npm run ui             # start the web UI at http://localhost:3000
```

## Web UI

Run `npm run ui` and open `http://localhost:3000`.

Filters available:
- Sources (Zillow, Redfin, Craigslist)
- Min/max bedrooms
- Min bathrooms
- Min/max monthly rent

## CLI (headless scrape)

```bash
node src/index.js
```

Scrapes all sources, prints results grouped by source, and exits.

## Project Structure

```
src/
  scrapers/
    zillow.js       # Zillow API
    redfin.js       # Redfin (Puppeteer)
    craigslist.js   # Craigslist (Puppeteer)
  agents/
    listingAgent.js # Claude AI listing analysis
  sheets/
    googleSheets.js # Google Sheets sync
  public/
    index.html      # Web UI
  server.js         # Express server for UI
  index.js          # CLI entry point
  config.js         # Search filters & preferences
```

## Environment Variables

Create a `.env` file with:

```
ANTHROPIC_API_KEY=
GOOGLE_SHEET_ID=
GOOGLE_SERVICE_ACCOUNT_JSON=
```

## GitHub Actions

Runs daily at 3:00 PM CST. Add these three repository secrets:
- `ANTHROPIC_API_KEY`
- `GOOGLE_SHEET_ID`
- `GOOGLE_SERVICE_ACCOUNT_JSON`
