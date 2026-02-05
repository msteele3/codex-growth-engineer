# Meta Ads Library Scraping Notes

This skill scrapes the public Meta Ads Library website using Playwright. The site is highly dynamic; selectors and data formats change frequently.

## Inputs

Expected advertiser URLs are Meta Ads Library "saved search" links that target a single advertiser:
- Must contain `search_type=page`
- Must contain `view_all_page_id=<PAGE_ID>`

Example:
`https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&media_type=all&search_type=page&view_all_page_id=311353912066626`

## High-Level Strategy

1. Open advertiser saved-search URL.
2. Scroll to load enough ad cards.
3. Extract (best-effort) for each ad card:
   - `ad_archive_id` (from `?id=` links)
   - "Started running on <date>" (from card text)
4. Rank by oldest active (today - start date), select top N.
5. For each selected ad, open details (`https://www.facebook.com/ads/library/?id=<ad_id>`), then extract:
   - Media URLs (image/video)
   - Visible ad copy text (best-effort)

## Common Failure Modes

- **No ads load**: Meta may require a consent click / geo / rate limit.
  - Run with `--headful --debug` and see if the page is blocked by modals.
- **Video download fails**:
  - Some videos are served via streaming playlists (`.m3u8`) or `blob:` URLs.
  - Prefer `video.currentSrc` or `<source src>` URLs; if only `blob:` exists, consider adding network interception to capture the actual MP4/HLS URL.
- **Too many non-creative images**:
  - Ads Library pages include UI icons and profile thumbnails.
  - Filter images by size and/or URL patterns.

## Debugging Tips

- Use `--headful --debug` to:
  - Keep the browser open longer.
  - Save `page.content()` dumps for selector tuning.
  - Capture screenshots around failures.

## Compliance / Guardrails

- Do not fetch or store landing page HTML.
- Be conservative with request rate and scrolling.
