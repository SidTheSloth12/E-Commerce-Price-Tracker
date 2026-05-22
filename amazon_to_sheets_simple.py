import os
import re
import sys

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

try:
    import requests
except ImportError:
    requests = None

try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
except ImportError:
    gspread = None
    ServiceAccountCredentials = None

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "").strip()
SCRAPERAPI_URL = "http://api.scraperapi.com"
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "AZ ASINs")
SHEET_TAB_NAME = os.getenv("SHEET_TAB_NAME", "Sheet1")
STATUS_UNAVAILABLE = "NA"
STATUS_SUPPRESSED = "S"

UNAVAILABLE_PATTERN = re.compile(
    r"currently unavailable|temporarily out of stock|out of stock|not available|unavailable|sold out|no longer available|could not find|does not exist|was not found|invalid asin|page not found",
    re.IGNORECASE,
)
CANONICAL_ASIN_PATTERN = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})", re.IGNORECASE)
PRICE_PATTERN = re.compile(r"[\u20b9₹]\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?", re.IGNORECASE)
BUY_BUTTON_PATTERN = re.compile(
    r"add-to-cart|buy-now|add-to-basket|atc-button|submit\.add|submit\.buy|id=\"add-to-cart|id=\"buy-now",
    re.IGNORECASE,
)
OFFER_LISTING_PATTERN = re.compile(r"Other sellers|See all buying options|See all offers", re.IGNORECASE)
REDIRECT_BLACKLIST = ("/gp/cart", "/gp/your-account", "/gp/help", "/gp/buy", "ref=nb_sb_noss")

def normalize_asin(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
def normalize_price(text):
    if not text:
        return ""
    text = text.replace("Rs.", "₹").replace("INR", "₹").replace("Rs", "₹")
    match = PRICE_PATTERN.search(text)
    if not match:
        return ""
    price = match.group(0)
    price = re.sub(r"[^\u20b9\u20b9₹0-9\.\,]", "", price)
    price = price.replace(",", "")
    if not price.startswith("₹"):
        price = f"₹{price}"
    return price


def fetch_amazon_html(asin):
    if requests is None:
        raise RuntimeError("Missing dependency: install requests")
    if not SCRAPERAPI_KEY:
        raise RuntimeError("Missing SCRAPERAPI_KEY environment variable")

    params = {
        "api_key": SCRAPERAPI_KEY,
        "url": f"https://www.amazon.in/dp/{asin}",
        "country_code": "IN",
        "render": "false",
    }
    response = requests.get(SCRAPERAPI_URL, params=params, timeout=30)
    return response


def classify_simple_html(asin, html, final_url):
    asin = normalize_asin(asin)
    if not html:
        return STATUS_SUPPRESSED

    final_url_lower = final_url.lower() if isinstance(final_url, str) else ""
    if any(token in final_url_lower for token in REDIRECT_BLACKLIST) or "/dp/" not in final_url_lower:
        return STATUS_SUPPRESSED

    if UNAVAILABLE_PATTERN.search(html):
        return STATUS_UNAVAILABLE

    canonical_match = CANONICAL_ASIN_PATTERN.search(html)
    if canonical_match and normalize_asin(canonical_match.group(1)) != asin:
        return STATUS_SUPPRESSED

    if re.search(r"looking for something|sorry!|we couldn't find|couldn't find any products", html, re.IGNORECASE):
        return STATUS_SUPPRESSED

    has_buy_button = BUY_BUTTON_PATTERN.search(html)
    has_offer_listing_only = OFFER_LISTING_PATTERN.search(html) and not has_buy_button
    
    if has_offer_listing_only:
        return STATUS_SUPPRESSED

    if has_buy_button:
        price = normalize_price(html)
        if price:
            return price

    return STATUS_UNAVAILABLE


def classify_asin(asin):
    asin = normalize_asin(asin)
    if not asin:
        return ""

    try:
        response = fetch_amazon_html(asin)
    except Exception:
        return STATUS_SUPPRESSED

    if response.status_code != 200:
        return STATUS_SUPPRESSED

    final_url = response.url
    return classify_simple_html(asin, response.text, final_url)


def read_asins_from_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def col_idx_to_a1_col(col_idx):
    letters = []
    while col_idx > 0:
        col_idx, rem = divmod(col_idx - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def open_google_sheet():
    if gspread is None or ServiceAccountCredentials is None:
        raise RuntimeError("Missing gspread/oauth2client dependency")

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_PATH, scope)
    client = gspread.authorize(creds)
    return client.open(GOOGLE_SHEET_NAME).worksheet(SHEET_TAB_NAME)


def load_asins_from_sheet(sheet):
    all_rows = sheet.get_all_values()
    if not all_rows:
        raise RuntimeError("Google Sheet is empty")

    header = all_rows[0]
    asin_col_idx = next((i for i, col in enumerate(header) if "asin" in col.lower()), 0)
    price_col_idx = asin_col_idx + 1
    if price_col_idx >= len(header) or not header[price_col_idx].strip():
        sheet.update_cell(1, price_col_idx + 1, "Price")

    rows = []
    for row_idx, row in enumerate(all_rows[1:], start=2):
        asin = row[asin_col_idx].strip() if asin_col_idx < len(row) else ""
        rows.append((row_idx, asin))
    return rows, price_col_idx


def update_google_sheet(sheet, results, price_col_idx):
    if not results:
        print("No rows to update.")
        return

    price_batch = [[status] for _, status in results]
    start_row = results[0][0]
    end_row = results[-1][0]
    target_range = f"{col_idx_to_a1_col(price_col_idx + 1)}{start_row}:{col_idx_to_a1_col(price_col_idx + 1)}{end_row}"
    sheet.update(range_name=target_range, values=price_batch)
    print("Google Sheet updated successfully.")


def main():
    if requests is None:
        print("Error: install requests before running this script.")
        return

    try:
        sheet = open_google_sheet()
    except Exception as e:
        print(f"Google Sheets authentication failed: {e}")
        return

    try:
        rows, price_col_idx = load_asins_from_sheet(sheet)
    except Exception as e:
        print(f"Sheet load failed: {e}")
        return

    if not rows:
        print("No ASINs found in the Google Sheet.")
        return

    results = []
    for row_idx, asin in rows:
        status = classify_asin(asin)
        print(f"Row {row_idx}: {asin or '<blank>'} -> {status}")
        results.append((row_idx, status))

    try:
        update_google_sheet(sheet, results, price_col_idx)
    except Exception as e:
        print(f"Google Sheets update failed: {e}")


if __name__ == "__main__":
    main()
