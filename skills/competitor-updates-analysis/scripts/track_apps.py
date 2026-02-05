#!/usr/bin/env python3

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import gzip
import html
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _today_local() -> str:
    return dt.date.today().isoformat()


def _json_dump(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_text_lines(path: pathlib.Path) -> list[str]:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines


def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "app"


def _fetch(url: str, *, timeout_s: int, headers: dict[str, str]) -> tuple[bytes, str, dict[str, str]]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
            info = {k.lower(): v for (k, v) in resp.headers.items()}
            final_url = resp.geturl()
    except urllib.error.HTTPError as e:
        # Some responses still contain useful bodies.
        raw = e.read() if hasattr(e, "read") else b""
        info = {k.lower(): v for (k, v) in getattr(e, "headers", {}).items()}
        final_url = getattr(e, "url", url)
        raise urllib.error.HTTPError(final_url, e.code, e.msg, e.hdrs, None) from e

    if info.get("content-encoding", "").lower() == "gzip":
        raw = gzip.decompress(raw)
    return raw, final_url, info


def _decode_html(raw: bytes, headers: dict[str, str]) -> str:
    ctype = headers.get("content-type", "")
    m = re.search(r"charset=([^;]+)", ctype, re.I)
    charset = m.group(1).strip() if m else "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _parse_itunes_lookup(app_id: str, *, country: str, timeout_s: int, headers: dict[str, str]) -> dict[str, Any]:
    url = f"https://itunes.apple.com/lookup?id={urllib.parse.quote(app_id)}&country={urllib.parse.quote(country)}"
    raw, _, resp_headers = _fetch(url, timeout_s=timeout_s, headers=headers)
    txt = raw.decode("utf-8", errors="replace")
    data = json.loads(txt)
    if not isinstance(data, dict) or "results" not in data:
        raise ValueError("Unexpected iTunes lookup JSON")
    results = data.get("results") or []
    if not results:
        raise ValueError("No results in iTunes lookup")
    # The first result is typically the app record.
    rec = results[0]
    if not isinstance(rec, dict):
        raise ValueError("Unexpected iTunes lookup result shape")
    rec["_lookup_url"] = url
    rec["_lookup_content_type"] = resp_headers.get("content-type", "")
    return rec


def _extract_apple_app_id(url: str) -> str | None:
    # Typical: https://apps.apple.com/us/app/foo/id123456789
    m = re.search(r"/id(\d+)", url)
    if m:
        return m.group(1)
    # Sometimes: id=123 in query params (rare)
    parsed = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(parsed.query)
    if "id" in q and q["id"]:
        if re.fullmatch(r"\d+", q["id"][0] or ""):
            return q["id"][0]
    return None


def _with_query_param(url: str, key: str, value: str) -> str:
    parsed = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    q = [(k, v) for (k, v) in q if k != key]
    q.append((key, value))
    new_query = urllib.parse.urlencode(q)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def _clean_ws(s: str) -> str:
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_in_app_purchases_from_html(page_html: str) -> list[dict[str, str]]:
    # Best-effort heuristic: find the "In-App Purchases" block and then extract line items with a price.
    # Apple frequently formats these with truncation divs; HTML is not stable.
    out: list[dict[str, str]] = []
    if "In-App Purchases" not in page_html:
        return out

    # Narrow the search to a window after the marker to reduce false positives.
    idx = page_html.find("In-App Purchases")
    window = page_html[idx : idx + 200_000] if idx >= 0 else page_html

    # Find likely "name ... $x.xx" occurrences.
    # Accept multiple currencies and comma decimals.
    price_re = re.compile(
        r">([^<>]{1,200}?)<[^>]{0,100}?>\s*"
        r"(?:US\\s*)?([\\$€£¥]|R\\$|CA\\$|A\\$)\\s*([0-9][0-9\\.,]{0,10})",
        re.I,
    )

    seen: set[tuple[str, str]] = set()
    for m in price_re.finditer(window):
        name = _clean_ws(m.group(1))
        currency_symbol = m.group(2).strip()
        amount = m.group(3).strip()
        price = f"{currency_symbol}{amount}"
        key = (name, price)
        if not name or key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "price": price})
        if len(out) >= 50:
            break
    return out


def _extract_subscription_price_points(iaps: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    # Heuristic: App Store lists subscriptions mixed with other IAPs.
    # We mark "subscription-like" when the name implies a plan or period.
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    period_re = re.compile(
        r"\b("
        r"week|weekly|month|monthly|year|yearly|annual|annually|"
        r"subscription|subscrip|pro|premium|plus|plan"
        r")\b",
        re.I,
    )
    for item in iaps:
        name = (item.get("name") or "").strip()
        price = (item.get("price") or "").strip()
        if not name or not price:
            continue
        if not period_re.search(name):
            continue
        key = (name, price)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "price": price})
    return out


@dataclasses.dataclass(frozen=True)
class Review:
    author: str
    title: str
    body: str
    rating: int | None
    date: str | None


def _extract_recent_reviews_from_html(page_html: str, *, max_reviews: int) -> list[Review]:
    # Best-effort extraction from the "see all reviews" view.
    # Look for common review container class names like "we-customer-review".
    reviews: list[Review] = []

    # Split into blocks around likely markers.
    blocks = re.split(r'we-customer-review|customer-review|we-customer-review__content', page_html, flags=re.I)
    if len(blocks) <= 1:
        return reviews

    # Work on smaller slices to avoid runaway regex times.
    for blk in blocks[1:]:
        if len(reviews) >= max_reviews:
            break
        snippet = blk[:40_000]

        # Rating often represented by aria-label like "5 out of 5".
        rating = None
        m_rating = re.search(r'aria-label="\\s*([0-5])\\s+out\\s+of\\s+5', snippet, flags=re.I)
        if m_rating:
            try:
                rating = int(m_rating.group(1))
            except ValueError:
                rating = None

        # Title is often in <h3> or similar.
        title = ""
        m_title = re.search(r"<h3[^>]*>([^<]{1,200})</h3>", snippet, flags=re.I)
        if m_title:
            title = _clean_ws(m_title.group(1))

        # Body is often in a paragraph-ish container; grab a conservative chunk.
        body = ""
        m_body = re.search(r'we-truncate[^>]*>\\s*<[^>]+>\\s*([^<]{20,2000})<', snippet, flags=re.I)
        if m_body:
            body = _clean_ws(m_body.group(1))
        else:
            # Fallback: first longer text span.
            m_body2 = re.search(r">([^<>]{40,2000})<", snippet)
            if m_body2:
                body = _clean_ws(m_body2.group(1))

        # Author sometimes appears near "by <name>".
        author = ""
        m_author = re.search(r"by\\s*</span>\\s*<span[^>]*>([^<]{1,80})</span>", snippet, flags=re.I)
        if m_author:
            author = _clean_ws(m_author.group(1))

        # Date sometimes in <time datetime="...">.
        date = None
        m_date = re.search(r'<time[^>]+datetime="([^"]{4,40})"', snippet, flags=re.I)
        if m_date:
            date = _clean_ws(m_date.group(1))

        if not (title or body):
            continue

        reviews.append(Review(author=author, title=title, body=body, rating=rating, date=date))

    return reviews


def _summarize_review_themes(reviews: list[dict[str, Any]]) -> dict[str, list[str]]:
    # Heuristic-only. The agent should refine with an LLM.
    positives: list[str] = []
    negatives: list[str] = []
    for r in reviews:
        txt = f"{r.get('title','')} {r.get('body','')}".lower()
        if any(w in txt for w in ["love", "great", "amazing", "perfect", "helpful", "easy", "awesome"]):
            positives.append(r.get("title") or r.get("body", "")[:80])
        if any(w in txt for w in ["hate", "bad", "bug", "crash", "broken", "terrible", "slow", "ads", "scam"]):
            negatives.append(r.get("title") or r.get("body", "")[:80])
    return {
        "positive_examples": [p for p in positives if p][:3],
        "negative_examples": [n for n in negatives if n][:3],
    }


def _load_previous_snapshot(app_dir: pathlib.Path, date_iso: str) -> tuple[str, dict[str, Any]] | None:
    if not app_dir.exists():
        return None
    candidates: list[tuple[str, pathlib.Path]] = []
    for p in app_dir.glob("*.json"):
        if p.name == "latest.json":
            continue
        d = p.stem
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) and d < date_iso:
            candidates.append((d, p))
    if not candidates:
        return None
    d, p = sorted(candidates, key=lambda t: t[0])[-1]
    return d, json.loads(p.read_text(encoding="utf-8"))


def _diff_snapshot(prev: dict[str, Any], cur: dict[str, Any]) -> dict[str, Any]:
    diff: dict[str, Any] = {}
    keys = [
        "total_reviews",
        "last_update_date",
        "version",
        "release_notes",
        "base_price",
        "in_app_purchases",
        "subscription_prices",
    ]
    for k in keys:
        if prev.get(k) != cur.get(k):
            diff[k] = {"from": prev.get(k), "to": cur.get(k)}
    return diff


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ").strip()


def _write_report(
    out_path: pathlib.Path,
    *,
    date_iso: str,
    app_results: list[dict[str, Any]],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append(f"# Competitor Updates Report ({date_iso})")
    lines.append("")
    lines.append("Generated by `skills/competitor-updates-analysis/scripts/track_apps.py`.")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| App | Store | Total Reviews | Last Update | Version | Base Price | Subscription Price Points | IAP Price Points | Reviews Fetched | Changed vs Previous |")
    lines.append("| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | --- |")
    for r in app_results:
        app = _md_escape(r.get("app_name") or r.get("app_key") or "app")
        store = _md_escape(r.get("store") or "")
        total_reviews = r.get("total_reviews")
        last_update = _md_escape(str(r.get("last_update_date") or ""))
        version = _md_escape(str(r.get("version") or ""))
        base_price = _md_escape(str(r.get("base_price") or ""))
        sub_count = len(r.get("subscription_prices") or [])
        iap_count = len(r.get("in_app_purchases") or [])
        reviews_count = len(r.get("recent_reviews") or [])
        changed = "yes" if (r.get("diff") or {}) else "no"
        lines.append(
            f"| {app} | {store} | {total_reviews if total_reviews is not None else ''} | {last_update} | {version} | {base_price} | {sub_count} | {iap_count} | {reviews_count} | {changed} |"
        )
    lines.append("")

    for r in app_results:
        lines.append(f"## {r.get('app_name') or r.get('app_key')}")
        lines.append("")
        lines.append(f"- Store: `{r.get('store')}`")
        lines.append(f"- URL: `{r.get('app_url')}`")
        if r.get("lookup_url"):
            lines.append(f"- iTunes lookup: `{r.get('lookup_url')}`")
        lines.append(f"- Snapshot: `{r.get('snapshot_path')}`")
        if r.get("previous_snapshot_path"):
            lines.append(f"- Previous snapshot: `{r.get('previous_snapshot_path')}`")
        lines.append("")

        if r.get("errors"):
            lines.append("### Errors")
            lines.append("")
            for e in r["errors"]:
                lines.append(f"- {e}")
            lines.append("")

        if r.get("diff"):
            lines.append("### Changes Detected (Script Diff)")
            lines.append("")
            for k, v in sorted((r["diff"] or {}).items()):
                lines.append(f"- `{k}`: {v.get('from')!r} -> {v.get('to')!r}")
            lines.append("")

        lines.append("### Release Notes (Latest)")
        lines.append("")
        rn = (r.get("release_notes") or "").strip()
        lines.append(rn if rn else "(missing)")
        lines.append("")

        lines.append("### Pricing")
        lines.append("")
        lines.append(f"- Base price: {r.get('base_price')!r}")
        subs = r.get("subscription_prices") or []
        if subs:
            lines.append("- Subscription price points (best-effort):")
            for item in subs[:20]:
                lines.append(f"  - {item.get('name')!r}: {item.get('price')!r}")
            if len(subs) > 20:
                lines.append(f"  - (and {len(subs) - 20} more)")
        else:
            lines.append("- Subscription price points: (missing or none detected)")
        iaps = r.get("in_app_purchases") or []
        if iaps:
            lines.append("- In-app purchases (best-effort):")
            for item in iaps[:20]:
                lines.append(f"  - {item.get('name')!r}: {item.get('price')!r}")
            if len(iaps) > 20:
                lines.append(f"  - (and {len(iaps) - 20} more)")
        else:
            lines.append("- In-app purchases: (missing or none detected)")
        lines.append("")

        lines.append("### Recent Reviews (Latest)")
        lines.append("")
        rr = r.get("recent_reviews") or []
        if not rr:
            lines.append("(missing)")
            lines.append("")
        else:
            for rev in rr:
                title = _clean_ws(str(rev.get("title") or ""))
                rating = rev.get("rating")
                author = _clean_ws(str(rev.get("author") or ""))
                date = _clean_ws(str(rev.get("date") or ""))
                body = _clean_ws(str(rev.get("body") or ""))
                lines.append(f"- {title!r} (rating={rating!r}, author={author!r}, date={date!r})")
                lines.append(f"  {body}")
            lines.append("")

        lines.append("### Theme Heuristics (Draft)")
        lines.append("")
        themes = r.get("review_themes") or {}
        pos = themes.get("positive_examples") or []
        neg = themes.get("negative_examples") or []
        lines.append(f"- Positive examples: {pos!r}")
        lines.append(f"- Negative examples: {neg!r}")
        lines.append("")

        lines.append("### Suggested Agent Inference Prompts")
        lines.append("")
        lines.append("- Identify concrete changes implied by release notes and pricing shifts.")
        lines.append("- Cluster recent reviews into 3-5 themes for love/hate, and cite examples.")
        lines.append("- Infer product bets and tradeoffs (e.g., monetization changes, UX changes, performance, reliability).")
        lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch and persist App Store competitor snapshots, then diff vs prior.")
    ap.add_argument("--urls-file", type=str, help="Path to a file with one App Store URL per line.")
    ap.add_argument("--url", action="append", default=[], help="App Store URL to track (repeatable).")
    ap.add_argument("--out-dir", type=str, default="data/update-tracker", help="Output directory for snapshots/reports.")
    ap.add_argument("--country", type=str, default="us", help="2-letter App Store country code for lookup/reviews URL building.")
    ap.add_argument("--date", type=str, default=_today_local(), help="Snapshot date (YYYY-MM-DD). Defaults to today local.")
    ap.add_argument("--timeout", type=int, default=25, help="Per-request timeout (seconds).")
    ap.add_argument("--max-reviews", type=int, default=5, help="Number of most recent reviews to attempt to capture.")
    ap.add_argument("--sleep", type=float, default=1.0, help="Seconds to sleep between apps.")
    args = ap.parse_args()

    date_iso = args.date
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_iso):
        raise SystemExit("--date must be YYYY-MM-DD")

    urls: list[str] = []
    if args.urls_file:
        urls.extend(_read_text_lines(pathlib.Path(args.urls_file)))
    urls.extend(args.url or [])
    urls = [u.strip() for u in urls if u.strip()]
    if not urls:
        raise SystemExit("Provide --urls-file or at least one --url.")

    out_dir = pathlib.Path(args.out_dir)
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": f"en-{args.country.upper()},en;q=0.9",
    }

    app_results: list[dict[str, Any]] = []
    for i, url in enumerate(urls):
        if i > 0 and args.sleep > 0:
            time.sleep(args.sleep)

        result: dict[str, Any] = {
            "store": None,
            "app_url": url,
            "country": args.country,
            "date": date_iso,
            "errors": [],
        }

        parsed = urllib.parse.urlparse(url)
        host = (parsed.netloc or "").lower()
        if host.endswith("apps.apple.com"):
            result["store"] = "apple-app-store"
            app_id = _extract_apple_app_id(url)
            if not app_id:
                result["errors"].append("Could not extract Apple app id from URL.")
                result["app_key"] = _slugify(url)
                app_results.append(result)
                continue
            result["app_id"] = app_id
            result["app_key"] = f"apple-{app_id}"

            # iTunes lookup (stable metadata).
            try:
                rec = _parse_itunes_lookup(app_id, country=args.country, timeout_s=args.timeout, headers=headers)
                result["lookup_url"] = rec.get("_lookup_url")
                result["app_name"] = rec.get("trackName")
                result["seller_name"] = rec.get("sellerName")
                result["version"] = rec.get("version")
                result["last_update_date"] = rec.get("currentVersionReleaseDate")
                result["release_notes"] = rec.get("releaseNotes")
                result["total_reviews"] = rec.get("userRatingCount")
                # Base price is in numeric `price`; `formattedPrice` sometimes is "Free".
                price = rec.get("price")
                currency = rec.get("currency")
                formatted = rec.get("formattedPrice")
                if formatted:
                    result["base_price"] = formatted
                elif price is not None and currency:
                    result["base_price"] = f"{price} {currency}"
                else:
                    result["base_price"] = None
            except Exception as e:
                result["errors"].append(f"iTunes lookup failed: {type(e).__name__}: {e}")

            # HTML scrape (IAP + reviews).
            html_errors: list[str] = []
            page_html = ""
            try:
                raw, final_url, resp_headers = _fetch(url, timeout_s=args.timeout, headers=headers)
                page_html = _decode_html(raw, resp_headers)
                result["final_url"] = final_url
            except Exception as e:
                html_errors.append(f"App page fetch failed: {type(e).__name__}: {e}")
            if html_errors:
                result["errors"].extend(html_errors)

            if page_html:
                try:
                    iaps = _extract_in_app_purchases_from_html(page_html)
                    result["in_app_purchases"] = iaps
                    result["subscription_prices"] = _extract_subscription_price_points(iaps)
                except Exception as e:
                    result["errors"].append(f"IAP parse failed: {type(e).__name__}: {e}")
            else:
                result["in_app_purchases"] = []
                result["subscription_prices"] = []

            # Reviews: prefer the see-all view to increase likelihood of containing review blocks.
            reviews_html = ""
            try:
                reviews_url = _with_query_param(url, "see-all", "reviews")
                raw, _, resp_headers = _fetch(reviews_url, timeout_s=args.timeout, headers=headers)
                reviews_html = _decode_html(raw, resp_headers)
                result["reviews_url"] = reviews_url
            except Exception as e:
                result["errors"].append(f"Reviews fetch failed: {type(e).__name__}: {e}")

            recent: list[dict[str, Any]] = []
            if reviews_html:
                try:
                    extracted = _extract_recent_reviews_from_html(reviews_html, max_reviews=args.max_reviews)
                    for r in extracted:
                        recent.append(dataclasses.asdict(r))
                except Exception as e:
                    result["errors"].append(f"Reviews parse failed: {type(e).__name__}: {e}")
            result["recent_reviews"] = recent
            result["review_themes"] = _summarize_review_themes(recent)

        else:
            result["store"] = "unknown"
            result["app_key"] = _slugify(f"{host}-{url}")
            result["errors"].append(f"Unsupported store host: {host!r}. Expected apps.apple.com.")

        # Persist snapshot for this app.
        app_key = result.get("app_key") or _slugify(url)
        app_dir = out_dir / "snapshots" / app_key
        snapshot_path = app_dir / f"{date_iso}.json"
        result["snapshot_path"] = str(snapshot_path)

        prev = _load_previous_snapshot(app_dir, date_iso)
        if prev:
            prev_date, prev_obj = prev
            result["previous_snapshot_date"] = prev_date
            result["previous_snapshot_path"] = str(app_dir / f"{prev_date}.json")
            result["diff"] = _diff_snapshot(prev_obj, result)
        else:
            result["diff"] = {}

        snapshot_obj = dict(result)
        snapshot_obj["fetched_at"] = dt.datetime.now().isoformat(timespec="seconds")
        _json_dump(snapshot_path, snapshot_obj)
        _json_dump(app_dir / "latest.json", snapshot_obj)

        app_results.append(result)

    # Write report.
    report_path = out_dir / "reports" / f"{date_iso}.md"
    _write_report(report_path, date_iso=date_iso, app_results=app_results)

    # Also print the report path for convenience.
    print(str(report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
