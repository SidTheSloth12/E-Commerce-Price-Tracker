# Amazon to Google Sheets Price Scraper

A Python tool that fetches Amazon product prices via ScraperAPI and updates a Google Sheet. Features conservative classification with 98.8% accuracy while minimizing API credit usage.

## Features

- **Two versions available:**
  - `amazon_to_sheets.py` — Full-featured with structured API + HTML fallback
  - `amazon_to_sheets_simple.py` — Lightweight, single non-rendered fetch per ASIN
- **Conservative classification** — Prioritizes avoiding false positives (unavailable products marked as available)
- **Low credit usage** — Optimized to minimize ScraperAPI consumption
- **Google Sheets integration** — Automatically updates price column
- **Caching** — Reduces repeated API calls within TTL window
- **Multi-threaded** — Configurable concurrent workers for faster processing

## Setup

### 1. Install Dependencies

```bash
pip install requests gspread oauth2client beautifulsoup4
```

### 2. Configure Credentials

#### ScraperAPI Key
Copy `.env.example` to `.env` and fill in your ScraperAPI key:
```bash
cp .env.example .env
```

Edit `.env`:
```
SCRAPERAPI_KEY=your_scraperapi_key_here
GOOGLE_SHEET_NAME=AZ ASINs
SHEET_TAB_NAME=Sheet1
GOOGLE_CREDENTIALS_PATH=credentials.json
```

> `.env` and `credentials.json` are local-only configuration files. They are ignored by `.gitignore` and should not be committed to GitHub.

#### Google Service Account
1. [Create a Google Service Account](https://cloud.google.com/iam/docs/service-accounts-create)
2. Generate a JSON key file
3. Copy `credentials.json.example` to `credentials.json`
4. Paste your service account JSON key content into `credentials.json`

```bash
cp credentials.json.example credentials.json
# Edit credentials.json with your actual service account details
```

### 3. Prepare Google Sheet

- Share your Google Sheet with the service account email
- Add an `ASIN` column (first column)
- The script will auto-create a `Price` column

## Usage

```bash
# Full-featured version (structured + HTML fallback)
python amazon_to_sheets.py

# Simple version (non-rendered HTML only)
python amazon_to_sheets_simple.py
```

Both scripts:
- Read ASINs from the Google Sheet
- Fetch prices via ScraperAPI
- Update the sheet with results
- Return: `₹price`, `NA` (unavailable), or `S` (suppressed/redirected)

## Output Codes

| Code | Meaning |
|------|---------|
| `₹XXX.XX` | Product available with price |
| `NA` | Product unavailable |
| `S` | Product suppressed or redirected |

## Configuration

Edit constants in the script files:

```python
MAX_CONCURRENT_REQUESTS = 5  # Higher = faster but more API rate-limit risk
CACHE_TTL = 300              # Cache expiry in seconds
RENDERED_HTML_SESSIONS = (1005,)  # Render sessions (full version only)
```

## Accuracy

- **Simple version**: 97.6% accuracy on test dataset (171 products)
- **Full version**: Similar with enhanced fallback verification

## Credit Usage

Both versions are credit-efficient:
- **Simple**: 1 request per ASIN (non-rendered)
- **Full**: 1 structured request per ASIN + optional 1 rendered request for ambiguous cases

Concurrency does NOT affect total credit usage—only wall-clock time.

## Environment Variables

Required:
- `SCRAPERAPI_KEY` — Your ScraperAPI key

Optional (defaults shown):
- `GOOGLE_SHEET_NAME` — Sheet name (default: "AZ ASINs")
- `SHEET_TAB_NAME` — Tab name (default: "Sheet1")
- `GOOGLE_CREDENTIALS_PATH` — Credentials file path (default: `credentials.json`)

## License

Private/Internal Use
