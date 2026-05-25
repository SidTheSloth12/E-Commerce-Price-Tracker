import sys
import time
import json
import threading
import random
import os
import re
import concurrent.futures
from html import unescape

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

try:
    from bs4 import BeautifulSoup
except ImportError:  # HTML fallback still has a regex parser if bs4 is unavailable.
    BeautifulSoup = None

# Reconfigure stdout to use UTF-8 to prevent Windows console UnicodeEncodeError
sys.stdout.reconfigure(encoding='utf-8')

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "").strip()
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Copy of AZ ASINs")
SHEET_TAB_NAME = os.getenv("SHEET_TAB_NAME", "Sheet1")
CACHE_FILE = "asin_cache.json"
_cache = {}
_cache_lock = threading.Lock()
_cache_loaded = False
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
}

STATUS_UNAVAILABLE = "NA"
STATUS_SUPPRESSED = "S"
STATUS_NOT_FOUND = "Price Not Found"
PROXY_AUTH_ERROR = "Proxy Error: Auth/Credits Expired"
LOGIC_VERSION = 3
MAX_CONCURRENT_REQUESTS = 5
CACHE_TTL = 300  # Reuse recent results for repeated debugging runs and reduce proxy usage.
RENDERED_HTML_SESSIONS = (1005,)
ASIN_RESULT_OVERRIDES = {}

CURRENT_PRICE_KEYS = (
    "buybox_price",
    "buy_box_price",
    "price_to_pay",
    "current_price",
    "sale_price",
    "deal_price",
    "offer_price",
    "listing_price",
    "final_price",
    "price",
    "amount",
    "value",
)

EXCLUDED_PRICE_KEYS = (
    "mrp",
    "list",
    "retail",
    "was",
    "strike",
    "savings",
    "discount",
    "coupon",
    "shipping",
    "delivery",
    "monthly",
    "installment",
    "points",
)

UNAVAILABLE_KEYWORDS = (
    "currently unavailable",
    "temporarily out of stock",
    "out of stock",
    "not available",
    "unavailable",
    "sold out",
    "no longer available",
    "discontinued",
    "does not exist",
    "invalid asin",
    "not found",
    "not released",
    "no featured offers available",
)

AVAILABLE_KEYWORDS = (
    "in stock",
    "available to ship",
    "ships from",
    "add to cart",
    "buy now",
)


def col_idx_to_a1_col(col_idx):
    """Convert a 1-based column index to an A1 column name."""
    letters = []
    while col_idx > 0:
        col_idx, rem = divmod(col_idx - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def _is_missing(value):
    return value is None or value == "" or value == [] or value == {}


def normalize_asin(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _has_key(obj, keys):
    if not isinstance(obj, dict):
        return False
    wanted = {k.lower() for k in keys}
    return any(str(k).lower() in wanted for k in obj.keys())


def _dict_get_any(obj, keys):
    if not isinstance(obj, dict):
        return None
    wanted = {k.lower(): k for k in keys}
    for key, value in obj.items():
        if str(key).lower() in wanted:
            return value
    return None


def _extract_canonical_asin(html):
    if not isinstance(html, str):
        return ""
    canonical_match = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if not canonical_match:
        return ""
    href = canonical_match.group(1)
    asin_match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", href, re.IGNORECASE)
    return normalize_asin(asin_match.group(1)) if asin_match else ""


def _is_excluded_price_key(key):
    lower = str(key).lower()
    return any(part in lower for part in EXCLUDED_PRICE_KEYS)


def normalize_price(value):
    """Normalize an actual selling price. List/MRP fields are filtered before this."""
    if value is None or isinstance(value, bool):
        return ""

    if isinstance(value, (int, float)):
        if value <= 0:
            return ""
        return f"\u20b9{float(value):.2f}"

    text = unescape(str(value)).replace("\xa0", " ").strip()
    if not text or not re.search(r"\d", text):
        return ""

    currency_match = re.search(r"(\u20b9|rs\.?|inr|\$|\u20ac|\u00a3)", text, re.IGNORECASE)
    number_match = re.search(r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)", text)
    if not number_match:
        return ""

    amount = number_match.group(1).replace(",", "")
    currency = currency_match.group(1) if currency_match else "\u20b9"
    if currency.lower() in ("rs", "rs.", "inr"):
        currency = "\u20b9"

    if "." not in amount:
        amount = f"{amount}.00"
    return f"{currency}{amount}"


def _extract_price_from_allowed_keys(obj, allowed_keys=CURRENT_PRICE_KEYS, deep=False):
    """Find a selling price while skipping MRP/list/retail/discount-like fields."""
    if _is_missing(obj):
        return ""

    if isinstance(obj, (str, int, float)):
        return normalize_price(obj)

    if isinstance(obj, list):
        for item in obj:
            price = _extract_price_from_allowed_keys(item, allowed_keys, deep=deep)
            if price:
                return price
        return ""

    if not isinstance(obj, dict):
        return ""

    lower_to_original = {str(k).lower(): k for k in obj.keys()}
    for key in allowed_keys:
        original = lower_to_original.get(key)
        if original is None or _is_excluded_price_key(original):
            continue
        price = _extract_price_from_allowed_keys(obj.get(original), allowed_keys, deep=True)
        if price:
            return price

    if deep:
        for key, value in obj.items():
            if _is_excluded_price_key(key):
                continue
            price = _extract_price_from_allowed_keys(value, allowed_keys, deep=True)
            if price:
                return price

    return ""


def _pricing_section(payload):
    if not isinstance(payload, dict):
        return None
    pricing = payload.get("pricing")
    if pricing is not None:
        return pricing
    product = payload.get("product")
    if isinstance(product, dict):
        return product.get("pricing")
    return None


def _buybox_section(payload, pricing=None):
    parents = [pricing, payload]
    if isinstance(payload, dict):
        parents.append(payload.get("product"))

    for parent in parents:
        value = _dict_get_any(
            parent,
            ("buybox_winner", "buy_box_winner", "buybox_offer", "buybox", "buy_box"),
        )
        if value is not None:
            return value
    return None


def _offers_section(payload, pricing=None):
    parents = [pricing, payload]
    if isinstance(payload, dict):
        parents.append(payload.get("product"))

    for parent in parents:
        value = _dict_get_any(parent, ("offers", "offers_list", "other_sellers", "sellers"))
        if value is not None:
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = _dict_get_any(value, ("offers", "items", "results"))
                if isinstance(nested, list):
                    return nested
                return [value]
    return None


def _collect_status_text(obj):
    pieces = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            lower = str(key).lower()
            if any(part in lower for part in ("availability", "available", "stock", "status", "message", "error")):
                pieces.append(str(value))
            if isinstance(value, (dict, list)):
                pieces.extend(_collect_status_text(value))
    elif isinstance(obj, list):
        for item in obj:
            pieces.extend(_collect_status_text(item))
    elif isinstance(obj, str):
        pieces.append(obj)
    return pieces


def _contains_suppression_signal(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            lower_key = str(key).lower()
            if lower_key in ("suppressed", "is_suppressed", "suppression", "suppressed_by_amazon"):
                if value is True or str(value).strip().lower() in ("true", "yes", "1", "suppressed"):
                    return True
            if isinstance(value, str) and re.search(r"\bsuppress(?:ed|ion)?\b", value, re.IGNORECASE):
                return True
            if isinstance(value, (dict, list)) and _contains_suppression_signal(value):
                return True
    elif isinstance(obj, list):
        return any(_contains_suppression_signal(item) for item in obj)
    elif isinstance(obj, str):
        return bool(re.search(r"\bsuppress(?:ed|ion)?\b", obj, re.IGNORECASE))
    return False


def _explicit_unavailable(payload):
    text = " ".join(_collect_status_text(payload)).lower()
    if any(keyword in text for keyword in UNAVAILABLE_KEYWORDS):
        return True

    if isinstance(payload, dict):
        for key, value in payload.items():
            lower = str(key).lower()
            if lower in ("is_available", "available", "in_stock", "is_in_stock", "buyable", "purchasable"):
                if value is False or str(value).strip().lower() in ("false", "no", "0"):
                    return True
            if isinstance(value, dict) and _explicit_unavailable(value):
                return True
    return False


def _explicit_available(payload):
    text = " ".join(_collect_status_text(payload)).lower()
    if any(keyword in text for keyword in AVAILABLE_KEYWORDS):
        return True

    if isinstance(payload, dict):
        for key, value in payload.items():
            lower = str(key).lower()
            if lower in ("is_available", "available", "in_stock", "is_in_stock", "buyable", "purchasable"):
                if value is True or str(value).strip().lower() in ("true", "yes", "1"):
                    return True
            if isinstance(value, dict) and _explicit_available(value):
                return True
    return False


def _offers_find_price(offers):
    if not isinstance(offers, list):
        return ""
    for offer in offers:
        price = _extract_price_from_allowed_keys(offer, deep=True)
        if price:
            return price
    return ""


def _payload_asin(payload):
    if not isinstance(payload, dict):
        return ""
    candidates = [
        payload.get("asin"),
        payload.get("ASIN"),
        payload.get("product_asin"),
    ]
    product = payload.get("product")
    if isinstance(product, dict):
        candidates.extend([product.get("asin"), product.get("ASIN"), product.get("product_asin")])
    product_information = payload.get("product_information")
    if isinstance(product_information, dict):
        candidates.extend(
            [
                product_information.get("asin"),
                product_information.get("ASIN"),
                product_information.get("product_asin"),
            ]
        )
    for candidate in candidates:
        if candidate:
            return normalize_asin(candidate)
    return ""


def _extract_scraperapi_error(payload):
    if not isinstance(payload, dict):
        return ""
    candidates = []
    for key in ("error", "errors", "message", "detail", "details", "reason"):
        value = payload.get(key)
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, list):
            candidates.extend(str(item) for item in value if item)
        elif isinstance(value, dict):
            candidates.extend(str(item) for item in value.values() if item)
        elif value not in (None, False):
            candidates.append(str(value))
    message = " ".join(candidates).strip()
    if not message:
        return ""
    lower = message.lower()
    auth_markers = (
        "api key",
        "apikey",
        "authentication",
        "auth",
        "unauthorized",
        "invalid key",
        "expired",
        "credit",
        "credits",
        "billing",
    )
    if any(marker in lower for marker in auth_markers):
        return PROXY_AUTH_ERROR
    return f"Proxy Error: {message[:120]}"


def classify_structured_product(http_status, payload, requested_asin=None):
    """Return (value, definitive). Definitive values should not need HTML fallback."""
    if http_status == 404:
        return STATUS_UNAVAILABLE, True
    if not isinstance(payload, dict):
        return STATUS_NOT_FOUND, False

    proxy_error = _extract_scraperapi_error(payload)
    if proxy_error:
        return proxy_error, True

    payload_asin = _payload_asin(payload)
    if requested_asin and payload_asin and payload_asin != normalize_asin(requested_asin):
        return STATUS_SUPPRESSED, True

    if _contains_suppression_signal(payload):
        return STATUS_SUPPRESSED, True

    pricing = _pricing_section(payload)
    buybox = _buybox_section(payload, pricing)
    offers = _offers_section(payload, pricing)

    offers_price = _offers_find_price(offers)
    buybox_key_present = _has_key(payload, ("buybox_winner", "buy_box_winner", "buybox_offer", "buybox", "buy_box")) or _has_key(pricing, ("buybox_winner", "buy_box_winner", "buybox_offer", "buybox", "buy_box"))
    offers_key_present = offers is not None
    unavailable = _explicit_unavailable(payload)
    available = _explicit_available(payload)

    if unavailable and not available:
        return STATUS_UNAVAILABLE, True

    buybox_price = _extract_price_from_allowed_keys(buybox, deep=True)
    if buybox_price:
        return buybox_price, True

    if unavailable and not offers_price:
        return STATUS_UNAVAILABLE, True

    if offers_price:
        if buybox is None:
            return STATUS_SUPPRESSED, True
        return STATUS_UNAVAILABLE, True

    if offers_key_present and not offers_price:
        return STATUS_UNAVAILABLE, True

    direct_price = ""
    for source in (pricing, payload.get("product") if isinstance(payload, dict) else None, payload):
        price = _extract_price_from_allowed_keys(source, deep=False)
        if price:
            direct_price = price
            break

    if direct_price and available:
        return direct_price, True
    if direct_price:
        return direct_price, False

    if unavailable:
        return STATUS_UNAVAILABLE, True

    return STATUS_NOT_FOUND, False


def classify_html_product(html, asin):
    if not html:
        return STATUS_NOT_FOUND

    lower = html.lower()
    if "captcha" in lower or "robot check" in lower or "enter the characters you see below" in lower:
        return "error: CAPTCHA"

    if BeautifulSoup is None:
        asin = normalize_asin(asin)
        availability_match = re.search(r'id=["\']availability["\'][\s\S]{0,500}', html, re.IGNORECASE)
        availability_text = re.sub(r"<[^>]+>", " ", availability_match.group(0)).lower() if availability_match else ""
        if any(keyword in availability_text for keyword in UNAVAILABLE_KEYWORDS):
            return STATUS_UNAVAILABLE
        asin_inputs = [
            normalize_asin(match)
            for match in re.findall(
                r'<input[^>]+(?:id|name)=["\']ASIN["\'][^>]+value=["\']([^"\']+)["\']',
                html,
                re.IGNORECASE,
            )
        ]
        if asin_inputs and asin not in asin_inputs:
            return STATUS_SUPPRESSED
        canonical_asin = _extract_canonical_asin(html)
        if canonical_asin and canonical_asin != asin:
            return STATUS_SUPPRESSED
        product_exists = bool(
            re.search(r'id=["\']productTitle["\']', html, re.IGNORECASE)
            or asin_inputs
            or re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+/dp/', html, re.IGNORECASE)
        )
        has_buy_button = bool(
            re.search(
                r'(id|name)=["\'](?:add-to-cart-button|buy-now-button|submit\.add-to-cart|submit\.buy-now)["\']',
                html,
                re.IGNORECASE,
            )
        )
        if has_buy_button:
            for marker in (
                "corePrice_feature_div",
                "price_inside_buybox",
                "newBuyBoxPrice",
                "apexPriceToPay",
                "tp_price_block_total_price_ww",
            ):
                marker_index = lower.find(marker.lower())
                if marker_index == -1:
                    continue
                segment = re.sub(r"<[^>]+>", " ", html[marker_index : marker_index + 2500])
                price = normalize_price(segment)
                if price:
                    return price
        if product_exists:
            return STATUS_UNAVAILABLE
        return STATUS_NOT_FOUND

    soup = BeautifulSoup(html, "html.parser")
    product_exists = bool(
        soup.select_one("#productTitle")
        or soup.select_one("input#ASIN")
        or soup.select_one("input[name='ASIN']")
        or soup.select_one("link[rel='canonical'][href*='/dp/']")
    )

    asin = normalize_asin(asin)
    asin_inputs = [normalize_asin(el.get("value", "")) for el in soup.select("input#ASIN,input[name='ASIN']")]
    if asin_inputs and asin not in asin_inputs:
        return STATUS_SUPPRESSED

    canonical_link = soup.select_one("link[rel='canonical']")
    if canonical_link:
        canonical_asin = normalize_asin(
            re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", canonical_link.get("href", ""), re.IGNORECASE).group(1)
            if re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", canonical_link.get("href", ""), re.IGNORECASE)
            else ""
        )
        if canonical_asin and canonical_asin != asin:
            return STATUS_SUPPRESSED

    active_asins = {
        normalize_asin(el.get("data-csa-c-asin", ""))
        for el in soup.select(
            "#corePrice_feature_div, #availability_feature_div, "
            "#availabilityInsideBuyBox_feature_div, #buybox, #desktop_buybox"
        )
        if el.get("data-csa-c-asin")
    }
    if active_asins and asin not in active_asins:
        return STATUS_SUPPRESSED

    def node_matches_requested_asin(node):
        for ancestor in [node, *node.parents]:
            candidate = ancestor.get("data-csa-c-asin") if hasattr(ancestor, "get") else None
            if candidate:
                return normalize_asin(candidate) == asin
        return True

    availability_text = " ".join(
        node.get_text(" ", strip=True)
        for node in soup.select("#availability, #outOfStock, #availabilityInsideBuyBox_feature_div")
    ).lower()
    if any(keyword in availability_text for keyword in UNAVAILABLE_KEYWORDS):
        return STATUS_UNAVAILABLE

    buy_button_selectors = (
        "input#add-to-cart-button",
        "input#buy-now-button",
        "input[name='submit.add-to-cart']",
        "input[name='submit.buy-now']",
        "button#add-to-cart-button",
        "button#buy-now-button",
    )
    has_buy_button = bool(soup.select_one(", ".join(buy_button_selectors)))

    price_selectors = (
        "#corePrice_feature_div span.a-offscreen",
        "#price_inside_buybox",
        "#newBuyBoxPrice",
        ".apexPriceToPay span.a-offscreen",
        "#tp_price_block_total_price_ww span.a-offscreen",
    )
    for selector in price_selectors:
        for node in soup.select(selector):
            if not node_matches_requested_asin(node):
                continue
            price = normalize_price(node.get_text(" ", strip=True))
            if price and has_buy_button:
                return price

    has_offer_listing = bool(
        soup.select_one("#olp_feature_div")
        or soup.select_one("#buybox-see-all-buying-choices")
        or soup.select_one("a[href*='/gp/offer-listing/']")
        or soup.select_one("a[href*='condition=']")
    )

    if product_exists and has_offer_listing:
        return STATUS_SUPPRESSED
    if product_exists:
        return STATUS_UNAVAILABLE

    if any(keyword in lower for keyword in ("looking for something", "page not found", "couldn't find that page")):
        return STATUS_SUPPRESSED
    return STATUS_NOT_FOUND

def fetch_amazon_price_via_proxy(task_data):
    """Fetch Amazon status/price through ScraperAPI and classify it conservatively."""
    row_idx, asin = task_data
    if not asin:
        return row_idx, ""
    if requests is None:
        return row_idx, "Error: missing requests dependency"
    if not SCRAPERAPI_KEY:
        return row_idx, "Error: missing SCRAPERAPI_KEY environment variable"
    asin = normalize_asin(asin)
    if asin in ASIN_RESULT_OVERRIDES:
        return row_idx, ASIN_RESULT_OVERRIDES[asin]

    proxy_url = "https://api.scraperapi.com/structured/amazon/product"
    html_proxy_url = "http://api.scraperapi.com"
    params = {
        "api_key": SCRAPERAPI_KEY,
        "asin": asin,
        "country_code": "IN",
        "tld": "in",
    }
    html_params = {
        "api_key": SCRAPERAPI_KEY,
        "url": f"https://www.amazon.in/dp/{asin}",
        "country_code": "IN",
        "render": "true",
    }
    max_retries = 2
    fallback_candidate = ""

    # lazy-load cache
    global _cache_loaded
    if not _cache_loaded:
        try:
            with _cache_lock:
                if os.path.exists(CACHE_FILE):
                    with open(CACHE_FILE, "r", encoding="utf-8") as f:
                        _cache.update(json.load(f))
        except Exception:
            pass
        _cache_loaded = True

    # check cache
    with _cache_lock:
        c = _cache.get(asin)
        if c:
            ts = c.get("ts", 0)
            if c.get("logic_version") == LOGIC_VERSION and time.time() - ts < CACHE_TTL:
                return row_idx, c.get("value", "")

    def remember(value):
        with _cache_lock:
            _cache[asin] = {"ts": time.time(), "value": value, "logic_version": LOGIC_VERSION}
        return row_idx, value

    for attempt in range(max_retries):
        try:
            # small jitter to reduce thundering herd
            if attempt:
                time.sleep(min(1.0, 0.1 * (2 ** (attempt - 1))) + random.random() * 0.2)
            response = requests.get(proxy_url, params=params, headers=REQUEST_HEADERS, timeout=70)
            if response.status_code == 403:
                return remember(PROXY_AUTH_ERROR)
            elif response.status_code == 404:
                return remember(STATUS_UNAVAILABLE)
            elif response.status_code == 429:
                if attempt < max_retries - 1:
                    print(f"   [!] Rate limit 429 on {asin}. Retrying ({attempt + 1}/{max_retries})...")
                    continue
                return remember("Proxy Error: 429")
            elif response.status_code == 499:
                if attempt < max_retries - 1:
                    print(f"   [!] Proxy 499 on {asin}. Retrying ({attempt + 1}/{max_retries})...")
                    continue
                return remember("Proxy Error: 499")
            elif response.status_code != 200:
                if attempt < max_retries - 1:
                    print(f"   [!] Status {response.status_code} on {asin}. Retrying ({attempt + 1}/{max_retries})...")
                    continue
                return remember(f"Error {response.status_code}")

            if "captcha" in response.text.lower() or "robot check" in response.text.lower() or "enter the characters you see below" in response.text.lower():
                if attempt < max_retries - 1:
                    print(f"   [!] CAPTCHA block on {asin}. Retrying ({attempt + 1}/{max_retries})...")
                    continue
                return remember("error: CAPTCHA")

            try:
                data = response.json()
            except ValueError:
                if attempt < max_retries - 1:
                    print(f"   [!] JSON parse failed for {asin}. Retrying ({attempt + 1}/{max_retries})...")
                    continue
                return remember("Error: JSON parse failed")

            value, definitive = classify_structured_product(response.status_code, data, requested_asin=asin)
            if definitive:
                return remember(value)
            if value in (STATUS_UNAVAILABLE, STATUS_SUPPRESSED):
                return remember(value)
            if value != STATUS_NOT_FOUND:
                fallback_candidate = value
            break

        except requests.exceptions.ReadTimeout:
            if attempt < max_retries - 1:
                print(f"   [!] Timeout on {asin}. Retrying ({attempt + 1}/{max_retries})...")
                continue
            return remember("Error: Timeout after retries")
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"   [!] Error on {asin}: {str(e)}. Retrying ({attempt + 1}/{max_retries})...")
                continue
            return remember(f"Error: {str(e)}")

    if not fallback_candidate:
        return remember(STATUS_UNAVAILABLE)

    # If the structured API only exposed a bare price-like value, verify against
    # the actual product page so list prices and suppressed listings do not look available.
    for attempt, session_number in enumerate(RENDERED_HTML_SESSIONS):
        try:
            if attempt:
                time.sleep(0.4 + random.random() * 0.2)
            request_params = dict(html_params)
            request_params["session_number"] = str(session_number)
            response = requests.get(html_proxy_url, params=request_params, headers=REQUEST_HEADERS, timeout=100)
            if response.status_code in (429, 499) and attempt < len(RENDERED_HTML_SESSIONS) - 1:
                print(
                    f"   [!] HTML fallback status {response.status_code} on {asin}. "
                    f"Rechecking ({attempt + 1}/{len(RENDERED_HTML_SESSIONS)})..."
                )
                continue
            if response.status_code == 403:
                return remember(PROXY_AUTH_ERROR)
            if response.status_code == 404:
                return remember(STATUS_UNAVAILABLE)
            if response.status_code != 200:
                if fallback_candidate:
                    return remember(fallback_candidate)
                return remember(f"Error {response.status_code}")

            html_value = classify_html_product(response.text, asin)
            if html_value != STATUS_NOT_FOUND:
                if html_value == STATUS_UNAVAILABLE and attempt < len(RENDERED_HTML_SESSIONS) - 1:
                    print(
                        f"   [!] HTML unavailable snapshot on {asin}. "
                        f"Rechecking ({attempt + 1}/{len(RENDERED_HTML_SESSIONS)})..."
                    )
                    continue
                return remember(html_value)
            if fallback_candidate:
                return remember(fallback_candidate)
            return remember(STATUS_UNAVAILABLE)
        except requests.exceptions.ReadTimeout:
            if attempt < len(RENDERED_HTML_SESSIONS) - 1:
                print(
                    f"   [!] HTML fallback timeout on {asin}. "
                    f"Rechecking ({attempt + 1}/{len(RENDERED_HTML_SESSIONS)})..."
                )
                continue
            if fallback_candidate:
                return remember(fallback_candidate)
            return remember("Error: Timeout after retries")
        except Exception as e:
            if attempt < len(RENDERED_HTML_SESSIONS) - 1:
                print(
                    f"   [!] HTML fallback error on {asin}: {str(e)}. "
                    f"Rechecking ({attempt + 1}/{len(RENDERED_HTML_SESSIONS)})..."
                )
                continue
            if fallback_candidate:
                return remember(fallback_candidate)
            return remember(f"Error: {str(e)}")

    return remember(fallback_candidate or STATUS_UNAVAILABLE)
def main():
    print("Connecting to Google Sheets...")
    if gspread is None or ServiceAccountCredentials is None:
        print("Authentication Error: missing gspread/oauth2client dependency. Install the sheet dependencies before running main().")
        return
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_PATH, scope)
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet(SHEET_TAB_NAME)
    except Exception as e:
        response = getattr(e, "response", None)
        status_code = getattr(response, "status_code", None)
        exc_name = type(e).__name__
        if exc_name == "SpreadsheetNotFound":
            print(
                "Google Sheets Error: spreadsheet not found or not shared with the service account. "
                f"Check GOOGLE_SHEET_NAME={GOOGLE_SHEET_NAME!r} and share it with the client_email in {GOOGLE_CREDENTIALS_PATH}."
            )
        elif exc_name == "WorksheetNotFound":
            print(f"Google Sheets Error: worksheet/tab {SHEET_TAB_NAME!r} was not found in {GOOGLE_SHEET_NAME!r}.")
        elif status_code:
            print(f"Google Sheets API Error ({status_code}): {e}")
        else:
            print(f"Google Sheets Authentication Error: {e}")
        return
    all_rows = sheet.get_all_values()
    if not all_rows:
        print("The sheet is empty.")
        return
    header = all_rows[0]
    asin_col_idx = None
    for i, col in enumerate(header):
        if "asin" in col.lower():
            asin_col_idx = i + 1
            break
    if asin_col_idx is None:
        print("Could not find 'ASIN' column header. Defaulting to Column 1.")
        asin_col_idx = 1
    price_col_idx = asin_col_idx + 1
    price_col_letter = col_idx_to_a1_col(price_col_idx)
    if len(header) < price_col_idx or all_rows[0][price_col_idx-1] == "":
        sheet.update_cell(1, price_col_idx, "Price")
    total_products = len(all_rows) - 1
    print(f"Multi-threading active ({MAX_CONCURRENT_REQUESTS} workers). Processing {total_products} products...")
    tasks = []
    for row_idx, row in enumerate(all_rows[1:], start=2):
        if len(row) < asin_col_idx:
            tasks.append((row_idx, ""))
        else:
            tasks.append((row_idx, row[asin_col_idx-1].strip()))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
        future_to_asin = {executor.submit(fetch_amazon_price_via_proxy, task): task for task in tasks}
        completed_count = 0
        for future in concurrent.futures.as_completed(future_to_asin):
            completed_count += 1
            row_idx, result_price = future.result()
            original_asin = next(t[1] for t in tasks if t[0] == row_idx)
            if original_asin:
                print(f"[{completed_count}/{total_products}] Finished {original_asin} -> {result_price}")
            results.append((row_idx, result_price))
    results.sort(key=lambda x: x[0])
    price_batch = [[r[1]] for r in results]
    print("\nAll items parsed! Uploading batch update block to Google Sheets...")
    target_range = f"{price_col_letter}2:{price_col_letter}{len(price_batch) + 1}"
    try:
        sheet.update(range_name=target_range, values=price_batch)
        print("Spreadsheet successfully updated!")
    except Exception as e:
        print(f"Failed to update spreadsheet: {e}")
    # persist cache to reduce repeated API calls in future runs
    try:
        with _cache_lock:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(_cache, f, ensure_ascii=False)
    except Exception:
        pass
if __name__ == "__main__":
    main()
