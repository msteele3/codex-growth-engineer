# Spec Format

Use a single JSON file as input to the uploader script.

Minimal required fields:
- `ad_account_id` (numeric, no `act_` prefix)
- `page_id`
- `ads[]` with `type`, `name`, `file`

All string IDs should be strings.

## Example

```json
{
  "graph_version": "v24.0",
  "ad_account_id": "730744483436372",
  "page_id": "807789605443819",
  "default": {
    "destination_url": "https://example.com",
    "cta_type": "LEARN_MORE",
    "primary_text": "Primary text goes here.",
    "headline": "Headline goes here.",
    "description": ""
  },
  "target": {
    "campaign_name": "Codex Draft Campaign",
    "adset_name": "Codex Draft Ad Set",
    "create_if_missing": true,
    "reuse_by_name": true,
    "campaign": {
      "objective": "TRAFFIC",
      "special_ad_categories": []
    },
    "adset": {
      "daily_budget": 100,
      "billing_event": "IMPRESSIONS",
      "optimization_goal": "LINK_CLICKS",
      "destination_type": "WEBSITE",
      "targeting": {
        "geo_locations": { "countries": ["US"] },
        "age_min": 18,
        "age_max": 65
      }
    }
  },
  "ads": [
    {
      "type": "image",
      "name": "Hackathon - Image 01",
      "file": "assets/ad-01.png"
    },
    {
      "type": "video",
      "name": "Hackathon - Video 01",
      "file": "assets/ad-01.mp4"
    }
  ]
}
```

## Target Resolution Rules

The script resolves where to put ads in this order:

1. If `target.adset_id` is present, use it.
2. Else if `target.adset_name` is present:
   - Resolve campaign:
     - If `target.campaign_id` is present, use it.
     - Else if `target.campaign_name` is present and `reuse_by_name=true`, search for an existing campaign with that name.
     - Else create a new campaign (if `create_if_missing=true`).
   - Resolve ad set:
     - If `reuse_by_name=true`, search for an existing ad set with `adset_name` under the resolved campaign.
     - Else create a new ad set (if `create_if_missing=true`).

If `target` is omitted entirely, the script uses:
- `campaign_name`: `Codex Draft Campaign`
- `adset_name`: `Codex Draft Ad Set`
- Safe ad set defaults (budget + targeting) as shown in the example.

## Per-Ad Overrides

Each entry in `ads[]` may override:
- `destination_url`
- `cta_type`
- `primary_text`
- `headline`
- `description`

## Notes

- This skill always creates `PAUSED` objects (campaign, ad set, ads).
- `ads[].file` paths are resolved relative to the spec file location unless you provide an absolute path.
- For Instagram placements you will typically need `ig_actor_id` and/or Page-to-IG linkage; this is intentionally out of scope for the first cut.
