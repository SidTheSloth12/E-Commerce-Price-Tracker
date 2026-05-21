import sys

sys.stdout.reconfigure(encoding="utf-8")
from amazon_to_sheets import fetch_amazon_price_via_proxy

TESTS = [
    ("B0FJT8JWRP", "NA"),
    ("B0FRGJWHJ7", "NA"),
    ("B0DRV5L8GC", "679"),
    ("B0GQZKRD5L", "NA"),
    ("B0GJ4724L4", "price"),
]

ok = True
for asin, exp in TESTS:
    results = [fetch_amazon_price_via_proxy((0, asin))[1] for _ in range(3)]
    if exp == "price":
        match = all(r and r[0] in "₹$" and r not in ("S", "NA") for r in results)
    elif exp == "679":
        match = all(r and "679" in r.replace(",", "") for r in results)
    else:
        match = all(r == exp for r in results)
    if not match:
        ok = False
    print(asin, "expected", exp, "got", results, "OK" if match else "FAIL")

print("ALL OK" if ok else "SOME FAILED")
