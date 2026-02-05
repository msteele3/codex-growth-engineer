# Scraping Notes (App Store)

This skill’s script uses best-effort scraping plus public endpoints. App Store HTML can change.

## Sources Used

- App Store web page (HTML): for "In-App Purchases" price points and recent reviews when available.
- iTunes Search API (JSON): for stable metadata like version, current version release date, and release notes when present.

## Field Expectations

- Total reviews:
  - Prefer iTunes Search API `userRatingCount` when present.
  - Otherwise attempt to infer from HTML.
- Last update date + changelog:
  - Prefer iTunes Search API `currentVersionReleaseDate` + `releaseNotes`.
  - Otherwise scrape "What’s New" section from HTML.
- Pricing points:
  - App base price from iTunes Search API `price` + `currency`.
  - In-app purchase price points scraped from HTML "In-App Purchases" list.
  - Subscription price points are a heuristic subset of IAPs based on SKU names (monthly/annual/plan/etc.).
- 5 most recent reviews:
  - Prefer review scraping from the `?see-all=reviews` view.
  - If reviews cannot be fetched/parsed, snapshot records the failure and continues.

## Operational Guidelines

- Use a realistic `User-Agent` and `Accept-Language`.
- Add small sleeps between apps (default: 1s).
- Treat missing fields as normal; do not fail the whole run for one app.
