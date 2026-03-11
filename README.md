# Chicago Apartment Finder

Scrapes Zillow, Redfin (Lincoln Park), and Craigslist for Chicago rentals. Includes a local web UI for searching with filters, and runs automatically every day at 3:00 PM CST via GitHub Actions.

## Sources
- **Zillow** — API-based, Chicago-wide
- **Redfin** — Lincoln Park neighborhood
- **Craigslist** — Chicago-wide, browser scrape

## Quick Start

```bash
pip3 install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env   # fill in your API keys
python3 src/server.py   # start the web UI at http://localhost:3000
```

## Daily Job (scrape + sync to Google Sheets)

```bash
python3 src/daily.py
```

Scrapes Redfin and Zillow using the filters in `src/config.py`, deduplicates results, and syncs them to your configured Google Sheet.

## Web UI

```bash
python3 src/server.py
```

Starts a local server at `http://localhost:3000` for searching with filters.

## Project Structure

```
src/
  scrapers/
    zillow.py         # Zillow API
    redfin.py         # Redfin (Playwright)
    craigslist.py     # Craigslist (Playwright)
  agent/
    listingsTool.py   # Scraper orchestration + deduplication
  sheets/
    google_sheets.py  # Google Sheets sync
  public/
    index.html        # Web UI
  server.py           # Flask server for UI
  main.py             # CLI entry point
  daily.py            # Daily job (scrape + sync)
  config.py           # Search filters & preferences
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
