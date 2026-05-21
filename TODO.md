- [x] Read and understand existing amazon_to_sheets.py
- [ ] Implement dynamic header lookup (exact 'ASIN' and 'Price') and fail fast if missing
- [ ] Replace ScraperAPI HTML proxy call with ScraperAPI structured JSON endpoint for Amazon India
- [ ] Implement exact 5-level state machine for INVALID ASIN / Unavailable / Suppressed / Price / Parsing Error
- [ ] Ensure strict row-to-row mapping from ASIN column to corresponding Price column
- [ ] Batch update the Price column once at the end (no per-row updates)
- [ ] Add request pacing (time.sleep) and robust JSON parsing
- [ ] Provide complete ready-to-run amazon_to_sheets.py
- [ ] Optional: quick local lint/run sanity check


