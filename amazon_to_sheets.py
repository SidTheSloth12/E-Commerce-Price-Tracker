import sys
import re
import time
import json
import concurrent.futures

import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Reconfigure stdout to use UTF-8 to prevent Windows console UnicodeEncodeError
sys.stdout.reconfigure(encoding="utf-8")

SCRAPERAPI_KEY = "0482406ecec73d1c704201e552e44c04"
GOOGLE_SHEET_NAME = "Copy of AZ ASINs"
SHEET_TAB_NAME = "Sheet1"
MAX_CONCURRENT_REQUESTS = 5
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9,en-US;q=0.8",
    "Accept": "application/json,text/plain,*/*;q=0.9",
}

SCRAPERAPI_URL_TEMPLATE = (
    "https://api.scraperapi.com/structured/amazon/product"
    "?api_key={api_key}&asin={asin}&country_code=in&tld=in"
)

PRICE_KEY_CANDIDATES = {
    "price",
    "listing_price",
    "offer_price",
    "sale_price",
    "buybox_price",
    "final_price",
    "amount",
}


def col_idx_to_a1_col(col_idx_1based: int) -> str:
    """1-based column index -> A1 notation column letter(s)."""
    if col_idx_1based < 1:
        raise ValueError("Column index must be >= 1")

    col = col_idx_1based
    letters = []
    while col > 0:
        col, rem = divmod(col - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def _norm_header(s: str) -> str:
    return (s or "").strip().lower()


def _extract_any_price_value(obj) -> str | None:
    """Best-effort extraction of a numeric price from a JSON subtree."""
    if obj is None:
        return None

    # Direct numeric/string
    if isinstance(obj, (int, float)):
        if int(obj) == obj:
            return str(int(obj))
        return str(obj)

    if isinstance(obj, str):
        t = obj.strip()
        # Extract number from strings like "₹499.00" or "499"
        m = re.search(r"(\d+[\d,]*)(?:\.(\d+))?", t)
        if m:
            whole = m.group(1).replace(",", "")
            frac = m.group(2)
            return whole if not frac else f"{whole}.{frac}"
        return None

    # Dict: look for known keys
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _norm_header(k) in PRICE_KEY_CANDIDATES:
                extracted = _extract_any_price_value(v)
                if extracted:
                    return extracted
        # Also recurse into values
        for v in obj.values():
            extracted = _extract_any_price_value(v)
            if extracted:
                return extracted

    # List/tuple: recurse
    if isinstance(obj, list):
        for item in obj:
            extracted = _extract_any_price_value(item)
            if extracted:
                return extracted

    return None


def _offers_has_valid_price(offers) -> bool:
    if not offers or not isinstance(offers, list):
        return False
    for offer in offers:
        price = _extract_any_price_value(offer)
        if price:
            return True
    return False


def _offers_find_valid_price(offers) -> str | None:
    if not offers or not isinstance(offers, list):
        return None
    for offer in offers:
        price = _extract_any_price_value(offer)
        if price:
            return price
    return None


def _json_indicates_explicit_unavailability(payload: dict) -> bool:
    # Exact checks via hierarchy criteria, but allow safe text fallbacks.
    availability_status = None
    if isinstance(payload, dict):
        availability_status = payload.get("availability_status")

    if isinstance(availability_status, str) and availability_status.strip() == "CURRENTLY_UNAVAILABLE":
        return True

    availability_text_fields = []
    if isinstance(payload, dict):
        availability = payload.get("availability")
        if isinstance(availability, str):
            availability_text_fields.append(availability)

        # Sometimes availability might exist deeper; collect a few common fields
        for k in ("availability_status", "availability", "stock_status", "in_stock"):
            v = payload.get(k)
            if isinstance(v, str):
                availability_text_fields.append(v)

    combined = " ".join(availability_text_fields).lower()
    if "currently unavailable" in combined or "out of stock" in combined:
        return True

    return False


def classify_scraperapi_result(http_status: int, payload: dict | None) -> str:
    """Implements the exact 5-level fallback hierarchy requested."""
    if http_status == 404:
        return "INVALID ASIN"

    payload = payload or {}

    # ScraperAPI schema (structured/amazon/product) tends to nest price-related
    # data under top-level "pricing".
    pricing = payload.get("pricing") if isinstance(payload, dict) else None
    if isinstance(pricing, dict):
        offers = pricing.get("offers")
        buybox_winner = pricing.get("buybox_winner")
        availability_status = pricing.get("availability_status")
    else:
        offers = None
        buybox_winner = None
        availability_status = payload.get("availability_status")

    offers_list = offers if isinstance(offers, list) else []

    # Rule 2: Explicit unavailability + offers array empty or missing
    tmp_payload = dict(payload)
    tmp_payload["availability_status"] = availability_status
    if _json_indicates_explicit_unavailability(tmp_payload) and len(offers_list) == 0:
        return "Unavailable"

    # Rule 3: buybox_winner missing/null/empty, but offers contains at least one offer with valid price
    buybox_missing = (
        buybox_winner is None
        or (isinstance(buybox_winner, str) and not buybox_winner.strip())
        or (isinstance(buybox_winner, dict) and not buybox_winner)
    )

    if buybox_missing and _offers_has_valid_price(offers_list):
        return "Suppressed"

    # Rule 4: buybox_winner exists and contains a valid price
    if not buybox_missing:
        bb_price = _extract_any_price_value(buybox_winner)
        if bb_price:
            return bb_price

    # Rule 5: Fallback/Parsing Error
    return "Parsing Error"


def fetch_price_for_asin(task_data):
    row_idx, asin = task_data

    if not asin:
        return row_idx, ""

    asin = str(asin).strip().upper()
    url = SCRAPERAPI_URL_TEMPLATE.format(api_key=SCRAPERAPI_KEY, asin=asin)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=60)
            http_status = resp.status_code

            # If ScraperAPI returns non-JSON for some statuses, still handle via hierarchy.
            payload = None
            try:
                payload = resp.json()
            except Exception:
                payload = None

            value = classify_scraperapi_result(http_status, payload)
            return row_idx, value
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                print(f"   [!] Request error on {asin}: {e}. Retrying ({attempt + 1}/{max_retries})...")
                time.sleep(2)
                continue
            return row_idx, f"Error: {str(e)}"

        finally:
            # pacing per attempt
            time.sleep(0.75)

    return row_idx, "Parsing Error"


def read_header_indices(sheet):
    all_rows = sheet.get_all_values()
    if not all_rows:
        raise ValueError("The sheet is empty.")

    header = all_rows[0]
    asin_col_idx_1based = None
    price_col_idx_1based = None

    for i, col in enumerate(header, start=1):
        norm = _norm_header(col)
        if norm == "asin":
            asin_col_idx_1based = i
        if norm == "price":
            price_col_idx_1based = i

    if asin_col_idx_1based is None:
        raise ValueError("Missing required header column: 'ASIN' (Row 1).")
    if price_col_idx_1based is None:
        raise ValueError("Missing required header column: 'Price' (Row 1).")

    return all_rows, asin_col_idx_1based, price_col_idx_1based


def main():
    print("Connecting to Google Sheets...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open(GOOGLE_SHEET_NAME).worksheet(SHEET_TAB_NAME)

    all_rows, asin_col_idx_1based, price_col_idx_1based = read_header_indices(sheet)

    price_col_letter = col_idx_to_a1_col(price_col_idx_1based)

    # Prepare tasks and result buffer in row order.
    tasks = []
    total_products = len(all_rows) - 1

    for row_number, row in enumerate(all_rows[1:], start=2):
        asin_val = ""
        if asin_col_idx_1based - 1 < len(row):
            asin_val = row[asin_col_idx_1based - 1].strip()
        tasks.append((row_number, asin_val))

    print(f"Multi-threading active ({MAX_CONCURRENT_REQUESTS} workers). Processing {total_products} products...")

    results_by_row = {}
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
        future_to_row = {executor.submit(fetch_price_for_asin, t): t for t in tasks}
        for future in concurrent.futures.as_completed(future_to_row):
            completed += 1
            row_idx, value = future.result()
            results_by_row[row_idx] = value
            asin_val = next((t[1] for t in tasks if t[0] == row_idx), "")
            if asin_val:
                print(f"[{completed}/{total_products}] Finished {asin_val} -> {value}")

    # Build batch column update (Rows 2..N) only in Price column.
    last_row_number = len(all_rows)
    price_values = []
    for r in range(2, last_row_number + 1):
        price_values.append([results_by_row.get(r, "")])

    target_range = f"{price_col_letter}2:{price_col_letter}{last_row_number}"
    print("\nUploading batch update block to Google Sheets...")
    sheet.update(range_name=target_range, values=price_values)
    print("Spreadsheet successfully updated!")


if __name__ == "__main__":
    main()

