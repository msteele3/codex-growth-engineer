---
name: meta-ads-library-tracker
description: Scrape Meta Ads Library advertiser saved-search URLs (facebook.com/ads/library/?...&search_type=page&view_all_page_id=...) to find the top N longest-running active ads, download their image/video creatives, extract video frames (1 fps) and audio, transcribe audio with the OpenAI API, and generate JSON/Markdown creative teardowns (hook, visual sequence, styling, color palette). Use when building an inspiration library for specific advertisers without downloading landing page HTML.
---

# Meta Ads Library Tracker

## Overview

Given one or more Meta Ads Library advertiser URLs (saved searches for a specific `view_all_page_id`), collect the **top 5 longest-running active ads** and generate a reusable inspiration bundle:
- Original creatives (images/videos)
- Video frames at 1 fps (first 30s)
- Extracted audio track (first 30s)
- Audio transcript (OpenAI transcription)
- LLM vision teardown of each image / video timeline + styling

## Quick Start

1. Create a text file with one advertiser URL per line:

```txt
https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&media_type=all&search_type=page&view_all_page_id=311353912066626
```

2. Run the tracker:

```bash
python3 skills/meta-ads-library-tracker/scripts/track_ads.py \
  --urls-file advertiser_urls.txt \
  --out-dir data/meta-ads-library \
  --top-n 5 \
  --max-video-seconds 30
```

## Requirements

- `OPENAI_API_KEY` set in the environment (for transcription + vision analysis).
- `ffmpeg` available on PATH (for frames + audio extraction).
- Python deps:

```bash
python3 -m pip install --upgrade openai pillow playwright
python3 -m playwright install chromium
```

## Outputs

By default (with `--out-dir data/meta-ads-library`):
- Per-advertiser snapshot JSON: `data/meta-ads-library/snapshots/<advertiser_key>/<YYYY-MM-DD>.json`
- Per-ad creative bundles: `data/meta-ads-library/creatives/<advertiser_key>/<ad_archive_id>/...`
- Daily report: `data/meta-ads-library/reports/<YYYY-MM-DD>.md`

## Agent Workflow

When asked to “pull the longest-running ads” for tracked advertisers:
1. Ask for a list/file of Meta Ads Library advertiser saved-search URLs (must include `view_all_page_id=...`).
2. Run `track_ads.py` with `--top-n 5` and `--max-video-seconds 30`.
3. Open the generated report and spot-check 1-2 creative bundles:
   - Confirm media downloaded (image/video present)
   - Confirm video has frames + audio + transcript
4. Summarize the key creative patterns across advertisers:
   - Hooks and opening beats
   - Visual motifs and layout patterns
   - Color palette + typography + motion style
   - CTA framing and offers

## Notes / Guardrails

- Do **not** fetch or store landing page HTML.
- Scraping is best-effort; Meta Ads Library markup changes. If selectors fail, rerun with `--headful --debug` and update `scripts/track_ads.py` heuristics.
