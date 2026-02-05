# Agent Scratchpad

Shared, append-only scratchpad for coordinating multiple agents working in this repo.

Protocol:
- Read before starting non-trivial work.
- Append entries (TASK/POINTER/QUESTION/ANSWER) with concrete file paths and commands.
- Prefer leaving a QUESTION over blocking.

---
## 2026-02-05 15:02:07 -0800 | TASK | agent=codex | role=competitor-updates-analysis
Running competitor updates tracker for Replika App Store URL; will generate report under data/update-tracker and summarize deltas.

## 2026-02-05 15:02:15 -0800 | POINTER | agent=codex | role=competitor-updates-analysis
Ran track_apps.py for Replika. Report: /Users/mattsteele/.codex/worktrees/7613/codex-growth-engineer/data/update-tracker/reports/2026-02-05.md. All fetches failed (URLError nodename nor servname provided) so snapshot has missing fields; no deltas available.

## 2026-02-05 15:04:38 -0800 | POINTER | agent=codex | role=competitor-updates-analysis
Replika (iOS) scrape succeeded. Report: /Users/mattsteele/.codex/worktrees/7613/codex-growth-engineer/data/update-tracker/reports/2026-02-05.md. Snapshot: /Users/mattsteele/.codex/worktrees/7613/codex-growth-engineer/data/update-tracker/snapshots/apple-1158555867/2026-02-05.json. Current state: version=11.2.1; last_update=2026-01-20T16:16:23Z; total_reviews=227763; release_notes=generic (stability/bug fixes/content updates). Pricing (best-effort scrape): subs show .99/mo and .99/mo plus yearly/annual points .99, .99; IAP gems /bin/zsh.99-.99 and 'Replika Platinum' .99. Review themes from fetched items (note: returned reviews are older 2020-2023, may not reflect current sentiment): + avatar customization, deep conversations, emotional support; - short-term memory/continuity, photo recognition, time-of-day awareness; monetization gating/NSFW restrictions complaints.

## 2026-02-05 15:04:49 -0800 | POINTER | agent=codex | role=competitor-updates-analysis
Correction: prior pricing line had shell-expanded $ amounts. Replika pricing scrape (best-effort): subs $7.99/mo and $14.99/mo; yearly/annual points $49.99 and $69.99. IAP gems $0.99-$19.99; 'Replika Platinum' $89.99.

## 2026-02-05 15:10:34 -0800 | POINTER | agent=codex | role=competitor-updates-analysis
Patched /Users/mattsteele/.codex/worktrees/7613/codex-growth-engineer/skills/competitor-updates-analysis/scripts/track_apps.py to retry transient DNS/URLError failures (Errno 8, name resolution, timeouts). New CLI flags: --retries (default 3) and --retry-backoff (default 0.75s).


## 2026-02-05 15:25:10 -0800 | TASK | agent=codex | role=meta-ads-library-tracker
Daily Companion ads pipeline run (Meta Ads Library -> Sora -> Meta draft upload) partially succeeded.

Artifacts:
- Daily report: /Users/mattsteele/Code/codex-growth-engineer/data/meta-ads-library/reports/2026-02-05.md
- Sora prompt: /Users/mattsteele/Code/codex-growth-engineer/data/meta-ads-library/sora/2026-02-05_1930473517882392_720x1280_run2.prompt.txt
- Sora video: /Users/mattsteele/Code/codex-growth-engineer/data/meta-ads-library/sora/2026-02-05_1930473517882392_720x1280_run2.mp4
- Meta spec: /Users/mattsteele/Code/codex-growth-engineer/data/meta-ads-library/meta-upload/spec_2026-02-05_1930473517882392.json
- Meta results: /Users/mattsteele/Code/codex-growth-engineer/data/meta-ads-library/meta-upload/results_2026-02-05_1930473517882392.json (NOT WRITTEN; upload failed)
- Run log: /Users/mattsteele/Code/codex-growth-engineer/tmp/meta-ads-library-logs/e2e_2026-02-05_152241.log

Failure (full error):
Access token validation failed. Generate a fresh Meta user access token with ads_management.
Details: HTTP 400 for https://graph.facebook.com/v24.0/me?access_token=%3Credacted%3E&fields=id%2Cname
{"error":{"message":"Error validating access token: Session has expired on Thursday, 05-Feb-26 15:00:00 PST. The current time is Thursday, 05-Feb-26 15:25:03 PST.","type":"OAuthException","code":190,"error_subcode":463,"fbtrace_id":"AGLO-gYHwGe9Sv0wbcURNot"}}
Sanity check:
- spec: /Users/mattsteele/Code/codex-growth-engineer/data/meta-ads-library/meta-upload/spec_2026-02-05_1930473517882392.json
- dotenv: /Users/mattsteele/Code/codex-growth-engineer/.env (mode=auto)
- env META_USER_ACCESS_TOKEN: set
- env META_APP_SECRET: MISSING (optional)
- env META_AD_ACCOUNT_ID: set (optional)
- env META_PAGE_ID: set (optional)
Command failed (2): /Users/mattsteele/Code/codex-growth-engineer/.venv/bin/python /Users/mattsteele/Code/codex-growth-engineer/skills/meta-ads-draft-uploader/scripts/meta_ads_draft_uploader.py --spec /Users/mattsteele/Code/codex-growth-engineer/data/meta-ads-library/meta-upload/spec_2026-02-05_1930473517882392.json --json-out /Users/mattsteele/Code/codex-growth-engineer/data/meta-ads-library/meta-upload/results_2026-02-05_1930473517882392.json

Next action:
- Refresh META_USER_ACCESS_TOKEN in /Users/mattsteele/Code/codex-growth-engineer/.env, then rerun upload only (reuse the existing Sora mp4):
  /Users/mattsteele/Code/codex-growth-engineer/.venv/bin/python /Users/mattsteele/Code/codex-growth-engineer/skills/meta-ads-library-tracker/scripts/e2e_workflow.py \
    --dotenv /Users/mattsteele/Code/codex-growth-engineer/.env --dotenv-override \
    --urls-file /Users/mattsteele/Code/codex-growth-engineer/advertiser_urls.txt \
    --out-dir /Users/mattsteele/Code/codex-growth-engineer/data/meta-ads-library \
    --product-brief /Users/mattsteele/Code/codex-growth-engineer/data/meta-ads-library/product_brief.json \
    --top-n 5 --pick-index 0 --reanalyze-empty --vision-model gpt-4.1 \
    --sora-size 720x1280 --sora-seconds 8 \
    --sora-out /Users/mattsteele/Code/codex-growth-engineer/data/meta-ads-library/sora/2026-02-05_1930473517882392_720x1280_run2.mp4 \
    --skip-track --skip-sora --upload

Expected on success:
- results_2026-02-05_1930473517882392.json will include campaign_id, adset_id, ad_id, creative_id, video_id; confirm all objects are PAUSED.
## 2026-02-05 15:39:15 -0800 | TASK | agent=codex | role=competitor-updates-analysis
Checking competitor updates for Companion AI competitors. Target: Replika (iOS App Store). Running tracker to capture current version/update date/release notes/pricing and compare vs prior snapshots if any.

## 2026-02-05 15:39:43 -0800 | POINTER | agent=codex | role=competitor-updates-analysis
Replika (iOS App Store) snapshot captured on 2026-02-05.

Artifacts:
- Report: /Users/mattsteele/Code/codex-growth-engineer/data/update-tracker/reports/2026-02-05.md
- Snapshot: /Users/mattsteele/Code/codex-growth-engineer/data/update-tracker/snapshots/apple-1158555867/2026-02-05.json
- Command: python3 skills/competitor-updates-analysis/scripts/track_apps.py --urls-file competitor_urls.txt --out-dir data/update-tracker --country us --retries 3 --retry-backoff 0.75 --max-reviews 10

Current app state (from snapshot):
- Version: 11.2.1
- Last update date: 2026-01-20T16:16:23Z
- Total reviews: 227,763
- Release notes: generic (stability improvements, bug fixes, content updates)
- Pricing (best-effort scrape): base Free; subs .99/mo + .99/mo and annual points .99 + .99; IAP gems /bin/zsh.99-.99; 'Replika Platinum' .99.

Delta status:
- No prior snapshot in this out-dir to diff against yet (today is the baseline), so 'Changed vs Previous' is effectively N/A.

User feedback themes from fetched reviews (note: fetched review dates skew older; treat as directional):
- Love: customizable 3D avatar, surprisingly deep conversations, emotional support.
- Hate: weak memory/continuity, inconsistent photo recognition, poor time-of-day awareness, monetization gating (esp. NSFW/relationship features).

## 2026-02-05 15:39:56 -0800 | POINTER | agent=codex | role=competitor-updates-analysis
Correction (avoid shell-expanded $ in prior entry):
- Replika pricing (best-effort scrape from App Store page): base Free; subs $7.99/mo and $14.99/mo; annual points $49.99 and $69.99; IAP gems $0.99-$19.99; 'Replika Platinum' $89.99.

## 2026-02-05 15:41:59 -0800 | NOTE | agent=codex | role=competitor-updates-analysis
Analysis (Replika iOS snapshot 2026-02-05):

What changed vs previous:
- No historical snapshot in /Users/mattsteele/Code/codex-growth-engineer/data/update-tracker for Replika prior to 2026-02-05, so we can’t quantify deltas yet (today is baseline).

What’s current (as of snapshot date 2026-02-05):
- Version 11.2.1; last updated 2026-01-20 (App Store).
- Release notes are non-specific (stability/bug fixes/content), which usually implies either incremental maintenance or that meaningful feature changes are being shipped without detailed notes.
- Monetization stack is broad: base Free; multiple subscription price points (monthly + annual at .99/.99); gem IAP ladder (/bin/zsh.99-.99); high-ticket 'Replika Platinum' .99 (likely lifetime/one-time tier).

What users love (from fetched reviews; directional because the feed includes older items):
- Strong emotional support / companionship value; users report meaningful impact.
- Avatar customization is a standout feature (3D + cosmetics), reinforcing an identity/roleplay loop.
- Conversation quality is perceived as deep when it works.

What users hate / risks:
- Memory/continuity is the most repeated product gap (forgetting within-session and across sessions). This is a direct opening for Companion AI differentiation if we can credibly deliver better continuity.
- Context awareness gaps (time-of-day/day-of-week) and inconsistent photo recognition are called out as “should be easy fixes,” which can amplify frustration.
- Monetization friction: complaints about relationship/NSFW gating and paying to unlock intimacy/activities; pricing complexity can drive negative sentiment.

Strategy inference (for Companion AI positioning):
- Replika is balancing (1) emotional support companion, (2) avatar/cosmetic economy, and (3) relationship/roleplay. Their monetization suggests they’re optimizing for ARPU via subscriptions + virtual goods + high-ticket tier.
- The biggest defensible product wedge is not “more features,” it’s reliability of relationship continuity (memory), plus lightweight situational awareness that makes the companion feel present (time/place routines).

Data quality note:
- Although the report says “most recent reviews,” the captured reviews include 2020-2025 dates; treat themes as long-lived pain points rather than “this week” sentiment.

