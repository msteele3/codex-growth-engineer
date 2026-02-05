#!/usr/bin/env python3
"""
Meta Graph API smoke tests (read-only).

Usage:
  META_USER_ACCESS_TOKEN="..." META_AD_ACCOUNT_ID="123..." python3 scripts/meta_graph_smoke_test.py

Optional:
  META_GRAPH_VERSION="v20.0"  (default: v20.0)
  META_PAGE_ID="123..."       (optional; checks page read access)
  META_BUSINESS_ID="123..."   (optional; query Business-owned Pages)
  META_APP_ID="..."           (optional; prints token app_id via /debug_token if META_APP_TOKEN is also provided)
  META_APP_TOKEN="APP_ID|APP_SECRET" (optional; for /debug_token; do NOT commit secrets)

This script avoids printing tokens and only performs GET requests.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def _env(name: str, required: bool = False) -> str | None:
    v = os.environ.get(name)
    if required and not v:
        print(f"Missing required env var: {name}", file=sys.stderr)
        sys.exit(2)
    return v


def _http_get_json(url: str, timeout_s: int = 30) -> dict:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = ""
        raise RuntimeError(f"HTTP {e.code} for {_redact_url(url)}\n{body}".strip()) from None
    except Exception as e:
        raise RuntimeError(f"Request failed for {_redact_url(url)}: {e}") from None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"Non-JSON response for {_redact_url(url)}:\n{data[:5000]}"
        ) from None


def _redact_url(url: str) -> str:
    """Redact sensitive query params (access tokens) from URLs before printing/logging."""
    try:
        p = urllib.parse.urlsplit(url)
        q = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        redacted = []
        for k, v in q:
            if k in {"access_token", "input_token", "appsecret_proof"}:
                redacted.append((k, "<redacted>"))
            else:
                redacted.append((k, v))
        query = urllib.parse.urlencode(redacted)
        return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, query, p.fragment))
    except Exception:
        return "<redacted_url>"


def _graph_get(version: str, path: str, params: dict[str, str]) -> dict:
    base = f"https://graph.facebook.com/{version}/{path.lstrip('/')}"
    qs = urllib.parse.urlencode(params)
    return _http_get_json(f"{base}?{qs}")


def _print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def _run_section(title: str, fn) -> None:
    _print_section(title)
    try:
        fn()
    except Exception as e:
        # Keep going so you can still diagnose partial access (e.g., Pages but not Ads).
        print(f"ERROR: {e}")


def main() -> int:
    version = _env("META_GRAPH_VERSION") or "v20.0"
    access_token = _env("META_USER_ACCESS_TOKEN") or _env("META_ACCESS_TOKEN")
    if not access_token:
        print(
            "Missing required env var: META_USER_ACCESS_TOKEN (or legacy META_ACCESS_TOKEN)",
            file=sys.stderr,
        )
        return 2
    ad_account_id = _env("META_AD_ACCOUNT_ID", required=True)
    page_id = _env("META_PAGE_ID")
    business_id = _env("META_BUSINESS_ID")
    app_token = _env("META_APP_TOKEN")
    app_secret = _env("META_APP_SECRET")
    pages_limit = int(_env("META_PAGES_LIMIT") or "25")

    def _with_common_params(p: dict[str, str]) -> dict[str, str]:
        p = dict(p)
        p["access_token"] = access_token
        # Optional hardening: appsecret_proof is recommended for client-side token usage.
        if app_secret:
            proof = hmac.new(
                app_secret.encode("utf-8"),
                msg=access_token.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()
            p["appsecret_proof"] = proof
        return p

    _run_section(
        "0) Config (sanity check)",
        lambda: print(
            json.dumps(
                {
                    "graph_version": version,
                    "ad_account_id": f"act_{ad_account_id}",
                    "business_id": business_id,
                    "page_id": page_id,
                    "appsecret_proof": bool(app_secret),
                    "pages_limit": pages_limit,
                    "debug_token_enabled": bool(app_token),
                },
                indent=2,
                sort_keys=True,
            )
        ),
    )

    _run_section(
        "1) /me (token is valid)",
        lambda: print(
            json.dumps(
                _graph_get(version, "/me", _with_common_params({"fields": "id,name"})),
                indent=2,
                sort_keys=True,
            )
        ),
    )

    def _perms():
        perms = _graph_get(version, "/me/permissions", _with_common_params({}))
        granted = []
        for p in perms.get("data", []) if isinstance(perms.get("data"), list) else []:
            if p.get("status") == "granted" and p.get("permission"):
                granted.append(p["permission"])
        print(json.dumps({"granted": sorted(granted)}, indent=2, sort_keys=True))

    _run_section("2) /me/permissions (scopes granted)", _perms)

    def _ad_account():
        act = _graph_get(
            version,
            f"act_{ad_account_id}",
            _with_common_params(
                {
                    "fields": ",".join(
                        [
                            "id",
                            "name",
                            "account_status",
                            "currency",
                            "timezone_name",
                            "business_name",
                            "amount_spent",
                            "spend_cap",
                        ]
                    ),
                }
            ),
        )
        print(json.dumps(act, indent=2, sort_keys=True))

    _run_section("3) Ad Account read (ads_read / ads_management + asset assignment)", _ad_account)

    def _my_adaccounts():
        acts = _graph_get(
            version,
            "/me/adaccounts",
            _with_common_params(
                {
                    "fields": "id,name,account_status,currency,timezone_name",
                    "limit": "50",
                }
            ),
        )
        print(json.dumps(acts, indent=2, sort_keys=True))

    _run_section("4) Ad accounts visible to this token (/me/adaccounts)", _my_adaccounts)

    def _campaigns():
        camps = _graph_get(
            version,
            f"act_{ad_account_id}/campaigns",
            _with_common_params(
                {
                    "fields": "id,name,status,effective_status,objective,created_time",
                    "limit": "5",
                }
            ),
        )
        print(json.dumps(camps, indent=2, sort_keys=True))

    _run_section("5) Campaign list (read-only)", _campaigns)

    def _pages():
        pages = _graph_get(
            version,
            "/me/accounts",
            _with_common_params(
                {
                    "fields": "id,name,category,tasks",
                    "limit": str(pages_limit),
                }
            ),
        )
        print(json.dumps(pages, indent=2, sort_keys=True))

    _run_section("6) Pages visible to this token (/me/accounts)", _pages)

    def _businesses():
        biz = _graph_get(
            version,
            "/me/businesses",
            _with_common_params(
                {
                    "fields": "id,name",
                    "limit": "25",
                }
            ),
        )
        print(json.dumps(biz, indent=2, sort_keys=True))

    _run_section("7) Businesses visible to this token (/me/businesses)", _businesses)

    if business_id:
        def _owned_pages():
            owned = _graph_get(
                version,
                f"/{business_id}/owned_pages",
                _with_common_params(
                    {
                        "fields": "id,name,category",
                        "limit": "50",
                    }
                ),
            )
            print(json.dumps(owned, indent=2, sort_keys=True))

        _run_section(
            "8) Business-owned Pages (requires META_BUSINESS_ID)",
            _owned_pages,
        )

        def _client_pages():
            client = _graph_get(
                version,
                f"/{business_id}/client_pages",
                _with_common_params(
                    {
                        "fields": "id,name,category",
                        "limit": "50",
                    }
                ),
            )
            print(json.dumps(client, indent=2, sort_keys=True))

        _run_section(
            "9) Business client Pages (requires META_BUSINESS_ID)",
            _client_pages,
        )

        def _owned_ad_accounts():
            owned = _graph_get(
                version,
                f"/{business_id}/owned_ad_accounts",
                _with_common_params(
                    {
                        "fields": "id,name,account_status",
                        "limit": "50",
                    }
                ),
            )
            print(json.dumps(owned, indent=2, sort_keys=True))

        _run_section(
            "10) Business-owned Ad Accounts (requires META_BUSINESS_ID)",
            _owned_ad_accounts,
        )

        def _client_ad_accounts():
            client = _graph_get(
                version,
                f"/{business_id}/client_ad_accounts",
                _with_common_params(
                    {
                        "fields": "id,name,account_status",
                        "limit": "50",
                    }
                ),
            )
            print(json.dumps(client, indent=2, sort_keys=True))

        _run_section(
            "11) Business client Ad Accounts (requires META_BUSINESS_ID)",
            _client_ad_accounts,
        )

    # Optional: Page read to check identity attachment prerequisites.
    if page_id:
        _run_section(
            "12) Page read (optional; id+name is public and does NOT prove page role)",
            lambda: print(
                json.dumps(
                    _graph_get(version, page_id, _with_common_params({"fields": "id,name"})),
                    indent=2,
                    sort_keys=True,
                )
            ),
        )

    # Optional: debug_token (requires app access token; best not to print raw token details)
    if app_token:
        def _dbg():
            dbg = _graph_get(
                version,
                "/debug_token",
                {"input_token": access_token, "access_token": app_token},
            )
            data = dbg.get("data", {}) if isinstance(dbg.get("data"), dict) else {}
            summary = {
                "app_id": data.get("app_id"),
                "type": data.get("type"),
                "is_valid": data.get("is_valid"),
                "expires_at": data.get("expires_at"),
                "scopes": sorted(data.get("scopes", []) or []),
                "granular_scopes": data.get("granular_scopes"),
                "user_id": data.get("user_id"),
            }
            print(json.dumps(summary, indent=2, sort_keys=True))

        _run_section("13) debug_token (optional; uses META_APP_TOKEN)", _dbg)

    _print_section("OK")
    print("Smoke tests completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
