---
name: competitor-updates-analysis
description: Track competitor app changes by fetching and scraping App Store (apps.apple.com) app pages given a list of URLs, persisting daily snapshots (review count, last update date, changelog/release notes, pricing points including in-app purchases when available, and 5 most recent reviews), and analyzing deltas vs prior snapshots to infer what users love/hate and what changed recently.
---

# Competitor Updates Analysis

Maintain a lightweight daily history of competitor app updates and user feedback, then generate a human-readable change analysis.

This skill bundles a script to:
- Fetch App Store pages for a list of app URLs
- Extract key fields (reviews, update date, release notes, pricing, recent reviews)
- Persist a per-day JSON snapshot per app
- Generate a markdown report comparing today vs the most recent prior snapshot

## Quick Start

1. Create a file with one app URL per line:

```txt
https://apps.apple.com/us/app/some-app/id123456789
https://apps.apple.com/us/app/other-app/id987654321
```

2. Run the tracker:

```bash
python3 skills/competitor-updates-analysis/scripts/track_apps.py \
  --urls-file competitor_urls.txt \
  --out-dir data/update-tracker \
  --country us \
  --retries 3 \
  --retry-backoff 0.75 \
  --max-reviews 10
```

Outputs:
- Snapshots: `data/update-tracker/snapshots/<app_key>/<YYYY-MM-DD>.json`
- Latest pointer: `data/update-tracker/snapshots/<app_key>/latest.json`
- Report: `data/update-tracker/reports/<YYYY-MM-DD>.md`

## Workflow For Analysis (Agent)

When asked to analyze competitor updates:
1. Run `track_apps.py` (or ask for the URLs file / list if missing).
2. Open the generated report and the latest+previous snapshots for any apps that changed.
3. Write an analysis section per app:
   - What changed (update date/version, release notes, pricing/IAPs, review volume)
   - What users love (themes from latest reviews)
   - What users hate (themes from latest reviews)
   - Inferences: what these changes imply about product strategy, risks, and opportunities
4. Call out uncertainty explicitly when fields are missing (App Store pages vary; scraping is best-effort).

## Notes

- This skill focuses on Apple App Store pages (`apps.apple.com`). Other stores can be added later.
- Be considerate with request rate; avoid hammering App Store pages.
- For scraping details and limitations, see `references/scraping-notes.md`.
