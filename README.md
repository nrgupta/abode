# Chicago Apartment Finder

Scrapes Zillow, Redfin, and Craigslist for Chicago rentals. Syncs listings to Google Sheets and sends daily email summaries. Runs automatically every day at 3:30 PM CST via launchd.

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

## Daily Job (scrape + sync to Google Sheets + email)

```bash
python3 src/daily.py
```

Scrapes Zillow and Redfin using the filters in `src/config.py`, deduplicates results, syncs new listings to Google Sheets, and sends an email summary to neilg2001@gmail.com.

### Automated Daily Runs

The job runs automatically every day at **3:30 PM** via launchd (macOS). To view logs:

```bash
tail -f ~/Desktop/apartment-finder/apartment-finder.log
```

To manually trigger:

```bash
launchctl start com.neilgupta.apartment-finder
```

To disable:

```bash
launchctl unload ~/Library/LaunchAgents/com.neilgupta.apartment-finder.plist
```

To re-enable:

```bash
launchctl load ~/Library/LaunchAgents/com.neilgupta.apartment-finder.plist
```

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
GOOGLE_SHEET_ID=your_sheet_id
GOOGLE_SERVICE_ACCOUNT_JSON=your_service_account_json
GMAIL_ADDRESS=your_gmail@gmail.com
GMAIL_APP_PASSWORD=your_16_char_app_password
```

### Gmail Setup

To enable email notifications:

1. Go to https://myaccount.google.com/apppasswords
2. Select "Mail" and "Windows (or your device)"
3. Generate a 16-character app password
4. Add it to `.env` as `GMAIL_APP_PASSWORD`

The app password format is: `xxxx xxxx xxxx xxxx` (4 groups of 4 characters with spaces)

## macOS Launchd Schedule

The daily job is scheduled via launchd to run at **3:30 PM every day**. Configuration file:

```
~/Library/LaunchAgents/com.neilgupta.apartment-finder.plist
```

The plist loads the config from your `.env` file and saves logs to:

```
~/Desktop/apartment-finder/apartment-finder.log
```
