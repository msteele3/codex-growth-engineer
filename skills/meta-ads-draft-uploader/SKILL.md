---
name: meta-ads-draft-uploader
description: Upload image ads and video ads to Meta (Facebook) Ads Manager using the Marketing API/Graph API. Create or reuse a Campaign + Ad Set (Meta “ad group”) and then create PAUSED (draft-safe) Ads from a JSON spec. Use when Codex needs to validate token/account access, upload ad images/videos, create AdCreatives (link_data/video_data) for a Page identity, and place the ads into an existing or newly created Ad Set.
---

# Meta Ads Draft Uploader

Create draft-safe (PAUSED) Meta ads from local media files.

This skill is intentionally scoped to speed and safety:
- Default everything to `PAUSED`.
- Use a single JSON spec file for batch creation.
- If a Campaign/Ad Set exists, reuse it; otherwise create them (unless explicitly disabled).

Terminology:
- Meta “ad group” == Meta “ad set”.

Safety invariant:
- Never create an `ACTIVE` campaign/ad set/ad. This skill always creates `PAUSED` objects only. Turn things on manually in Ads Manager after review.

## Quick Start

1. Create a spec JSON (example in `references/spec.md`).
2. Export your token (do not paste tokens into chat):

```bash
export META_USER_ACCESS_TOKEN="EAAB..."
```

3. Run:

```bash
python3 skills/meta-ads-draft-uploader/scripts/meta_ads_draft_uploader.py \
  --spec path/to/spec.json
```

Outputs:
- Prints a per-ad summary (uploaded asset IDs/hashes, creative ID, ad ID).
- Optionally writes a JSON result file via `--json-out results.json`.

## Workflow (Agent)

When asked to upload new image/video ads to a draft campaign:
1. Ask for (or locate) the target `ad_account_id` and `page_id`.
2. If the user has an existing Campaign/Ad Set they want to use, ask for either:
   - IDs (`campaign_id`, `adset_id`), or
   - Names (`campaign_name`, `adset_name`) so the script can find-or-create them.
3. Ensure the token has `ads_management` (or at least `ads_read` for diagnosis).
4. Create a `spec.json` with all creatives and media file paths. If no `target` is provided, the script will use safe defaults and create/reuse `Codex Draft Campaign` + `Codex Draft Ad Set`.
5. Run the script with `--dry-run` first if the user is nervous about API changes.
6. Run the script for real. If any call fails, use the error + `references/troubleshooting.md` to identify whether it is a wrong ad account ID, missing asset sharing (Page/ad account access), missing permission scopes, or video processing delay.
7. Keep objects `PAUSED`. If the user wants delivery, instruct them to activate in Ads Manager (this skill does not activate).

## Files

- Script: `scripts/meta_ads_draft_uploader.py`
- Spec format + examples: `references/spec.md`
- API calls to find IDs: `references/api-cheatsheet.md`
- Troubleshooting: `references/troubleshooting.md`
