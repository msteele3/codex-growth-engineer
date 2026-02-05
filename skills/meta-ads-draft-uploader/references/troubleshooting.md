# Troubleshooting

Common failure modes when creating draft ads via the Marketing API.

## 403 (#200) Missing ads_read / ads_management

This usually means either:
- The token does not include `ads_read` or `ads_management`, or
- The user behind the token is not assigned to the ad account you are calling

Fast checks:
- `GET /me/permissions`
- `GET /me/adaccounts?fields=id,name`

## /me/accounts is empty but you know the Page exists

`/me/accounts` only lists Pages where the user has a direct Page role.

If the Page is only visible via Business Manager, query it via the Business:
- `GET /me/businesses?fields=id,name`
- `GET /{business_id}/owned_pages?fields=id,name`
- `GET /{business_id}/client_pages?fields=id,name`

## Video uploads succeed but creatives fail

Videos often need time to process.

Poll the AdVideo node until ready:
- `GET /{video_id}?fields=status,permalink_url`

If the status indicates an error, try a different codec/container or a shorter video.

## Creative creation fails with Page/identity errors

The token must be able to use the Page as an ad identity for that ad account.

Fix in Business Settings:
- Assign the Page to the Business
- Share the Page asset to the user/system user
- Ensure the ad account can use the Page

Note:
- `GET /{page_id}?fields=id,name` can succeed even if you do not have a Page role (it is often public data). The real test is whether creating an AdCreative with that `page_id` succeeds.

## "Ads creative post was created by an app that is in development mode"

If you see an error like:
- "Ads creative post was created by an app that is in development mode. It must be in public to create this ad."

Fix:
- Switch your Meta developer app to Live/Public mode, or
- Use a user access token issued for a Live app (for hackathons, a token created via Graph API Explorer can work).

## Rate limits

Retry with exponential backoff when Meta returns transient errors.
