# API Cheatsheet (Graph API Explorer)

Use these calls to find the IDs you need for a `spec.json`.

Assume you already have a user/system access token with at least `ads_read` and the user is assigned to the assets.

## Ad Accounts

List ad accounts you can access:

```
/me/adaccounts?fields=id,name,account_status,currency,timezone_name&limit=50
```

Use the numeric portion of `act_<id>` as `ad_account_id`.

## Businesses (if assets are only visible under Business Manager)

List businesses:

```
/me/businesses?fields=id,name&limit=25
```

## Pages

Pages directly accessible by the user:

```
/me/accounts?fields=id,name,category,tasks&limit=25
```

Pages owned by a business:

```
/{business_id}/owned_pages?fields=id,name,category&limit=50
```

Pages shared to a business:

```
/{business_id}/client_pages?fields=id,name,category&limit=50
```

## Campaigns / Ad Sets

List campaigns:

```
/act_{ad_account_id}/campaigns?fields=id,name,status,effective_status&limit=50
```

List ad sets:

```
/act_{ad_account_id}/adsets?fields=id,name,campaign_id,status,effective_status&limit=50
```

## Ad Set Targeting Defaults Used By The Script

If you do not provide `target.adset.targeting`, the script uses:

```json
{
  "geo_locations": { "countries": ["US"] },
  "age_min": 18,
  "age_max": 65
}
```

