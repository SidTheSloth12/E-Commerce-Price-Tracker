import sys

sys.stdout.reconfigure(encoding="utf-8")

from amazon_to_sheets import (
    STATUS_UNAVAILABLE,
    STATUS_SUPPRESSED,
    classify_html_product,
    classify_structured_product,
    normalize_price,
)


def check(name, actual, expected):
    if actual != expected:
        raise AssertionError(f"{name}: expected {expected!r}, got {actual!r}")
    print(f"{name}: OK")


check("rupee numeric format", normalize_price(679), "\u20b9679.00")

check(
    "structured unavailable wins over stale buybox price",
    classify_structured_product(
        200,
        {
            "asin": "B0TEST1234",
            "availability_status": "Currently unavailable",
            "pricing": {"buybox_winner": {"price": "\u20b9679"}},
        },
        requested_asin="B0TEST1234",
    ),
    (STATUS_UNAVAILABLE, True),
)

check(
    "structured offers without buybox are not available",
    classify_structured_product(
        200,
        {
            "asin": "B0TEST1234",
            "pricing": {
                "buybox_winner": {},
                "offers": [{"price": "\u20b9679"}],
            },
        },
        requested_asin="B0TEST1234",
    ),
    (STATUS_UNAVAILABLE, True),
)

check(
    "structured buybox price is available",
    classify_structured_product(
        200,
        {
            "asin": "B0TEST1234",
            "availability": "In stock",
            "pricing": {"buybox_winner": {"price": "\u20b9679"}},
        },
        requested_asin="B0TEST1234",
    ),
    ("\u20b9679.00", True),
)

check(
    "html price requires buy button",
    classify_html_product(
        """
        <html>
          <span id="productTitle">Test Product</span>
          <input id="ASIN" value="B0TEST1234">
          <div id="corePrice_feature_div"><span class="a-offscreen">\u20b9679</span></div>
        </html>
        """,
        "B0TEST1234",
    ),
    STATUS_UNAVAILABLE,
)

check(
    "html buyable price is available",
    classify_html_product(
        """
        <html>
          <span id="productTitle">Test Product</span>
          <input id="ASIN" value="B0TEST1234">
          <input id="add-to-cart-button">
          <div id="corePrice_feature_div"><span class="a-offscreen">\u20b9679</span></div>
        </html>
        """,
        "B0TEST1234",
    ),
    "\u20b9679.00",
)
check(
    "html canonical mismatch is suppressed",
    classify_html_product(
        """
        <html>
          <span id="productTitle">Test Product</span>
          <input id="ASIN" value="B0TEST1234">
          <link rel="canonical" href="https://www.amazon.in/dp/B0OTHER1234">
        </html>
        """,
        "B0TEST1234",
    ),
    STATUS_SUPPRESSED,
)
print("ALL OFFLINE CLASSIFIER CHECKS OK")
