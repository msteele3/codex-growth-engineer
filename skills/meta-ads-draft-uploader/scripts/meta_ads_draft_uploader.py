#!/usr/bin/env python3
"""
Create draft-safe (PAUSED) Meta ads from a JSON spec.

This script:
- Uploads images (adimages) or videos (advideos) to an Ad Account
- Creates AdCreatives for a Page identity (link_data for images, video_data for videos)
- Creates (or reuses) a PAUSED Campaign + Ad Set when needed
- Creates PAUSED Ads in the resolved Ad Set

Requirements:
- Python 3.10+
- A user/system access token with ads_management

Usage:
  META_USER_ACCESS_TOKEN="..." python3 skills/meta-ads-draft-uploader/scripts/meta_ads_draft_uploader.py --spec spec.json
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _json_dumps(x: Any) -> str:
    return json.dumps(x, separators=(",", ":"), ensure_ascii=True)


def _merge_defaults(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    out = dict(defaults)
    for k, v in overrides.items():
        if v is not None:
            out[k] = v
    return out


def _as_dict(x: Any, what: str) -> dict[str, Any]:
    if x is None:
        return {}
    if not isinstance(x, dict):
        _die(f"{what} must be an object.")
    return x


def _as_list(x: Any, what: str) -> list[Any]:
    if not isinstance(x, list):
        _die(f"{what} must be an array.")
    return x


def _get_str(d: dict[str, Any], key: str, default: str = "") -> str:
    v = d.get(key, default)
    if v is None:
        return default
    return str(v)


def _get_bool(d: dict[str, Any], key: str, default: bool) -> bool:
    v = d.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y"}
    if isinstance(v, (int, float)):
        return bool(v)
    return default


def _get_int(d: dict[str, Any], key: str, default: int) -> int:
    v = d.get(key, default)
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str) and v.strip():
        try:
            return int(v)
        except ValueError:
            return default
    return default


def _redact_url(url: str) -> str:
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


def _http_json(req: urllib.request.Request, timeout_s: int = 60) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = ""
        raise RuntimeError(f"HTTP {e.code} for {_redact_url(req.full_url)}\n{body}".strip()) from None
    except Exception as e:
        raise RuntimeError(f"Request failed for {_redact_url(req.full_url)}: {e}") from None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"Non-JSON response for {_redact_url(req.full_url)}:\n{raw[:5000]}") from None


def _encode_multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes]]) -> tuple[bytes, str]:
    """
    fields: {name: value}
    files: {name: (filename, content_bytes)}
    """
    boundary = "----codex-meta-" + "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(24))
    crlf = b"\r\n"
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}".encode("utf-8"))
        body.extend(crlf)
        body.extend(f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"))
        body.extend(crlf)
        body.extend(crlf)
        body.extend(value.encode("utf-8"))
        body.extend(crlf)

    for name, (filename, content) in files.items():
        body.extend(f"--{boundary}".encode("utf-8"))
        body.extend(crlf)
        body.extend(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode("utf-8")
        )
        body.extend(crlf)
        body.extend(b"Content-Type: application/octet-stream")
        body.extend(crlf)
        body.extend(crlf)
        body.extend(content)
        body.extend(crlf)

    body.extend(f"--{boundary}--".encode("utf-8"))
    body.extend(crlf)
    return bytes(body), f"multipart/form-data; boundary={boundary}"


@dataclass(frozen=True)
class MetaConfig:
    graph_version: str
    access_token: str
    app_secret: str | None


class MetaGraph:
    def __init__(self, cfg: MetaConfig, *, dry_run: bool) -> None:
        self._cfg = cfg
        self._dry_run = dry_run

    def _base(self) -> str:
        return f"https://graph.facebook.com/{self._cfg.graph_version}"

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def _common_params(self) -> dict[str, str]:
        p = {"access_token": self._cfg.access_token}
        if self._cfg.app_secret:
            proof = hmac.new(
                self._cfg.app_secret.encode("utf-8"),
                msg=self._cfg.access_token.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()
            p["appsecret_proof"] = proof
        return p

    def get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        q = dict(self._common_params())
        q.update(params)
        url = f"{self._base()}/{path.lstrip('/')}?{urllib.parse.urlencode(q)}"
        if self._dry_run:
            return {"dry_run": True, "method": "GET", "url": _redact_url(url)}
        return _http_json(urllib.request.Request(url, method="GET"))

    def post_form(self, path: str, data: dict[str, str]) -> dict[str, Any]:
        d = dict(self._common_params())
        d.update(data)
        body = urllib.parse.urlencode(d).encode("utf-8")
        url = f"{self._base()}/{path.lstrip('/')}"
        if self._dry_run:
            return {
                "dry_run": True,
                "method": "POST",
                "url": url,
                "data": {
                    k: ("<redacted>" if k in {"access_token", "appsecret_proof"} else v)
                    for k, v in d.items()
                },
            }
        req = urllib.request.Request(url, method="POST", data=body)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        return _http_json(req)

    def post_multipart(self, path: str, fields: dict[str, str], files: dict[str, tuple[str, bytes]]) -> dict[str, Any]:
        f = dict(self._common_params())
        f.update(fields)
        body, content_type = _encode_multipart(f, files)
        url = f"{self._base()}/{path.lstrip('/')}"
        if self._dry_run:
            return {
                "dry_run": True,
                "method": "POST",
                "url": url,
                "fields": {
                    k: ("<redacted>" if k in {"access_token", "appsecret_proof"} else v)
                    for k, v in f.items()
                },
                "files": {k: v[0] for k, v in files.items()},
            }
        req = urllib.request.Request(url, method="POST", data=body)
        req.add_header("Content-Type", content_type)
        return _http_json(req, timeout_s=300)


def _retry(fn, *, tries: int = 5, base_sleep_s: float = 1.0) -> Any:
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            sleep_s = base_sleep_s * (2**i) + random.random() * 0.25
            time.sleep(sleep_s)
    raise last  # type: ignore[misc]

def _dry_id(prefix: str, name: str) -> str:
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    return f"dry_{prefix}_{h}"


def _paged_get(g: MetaGraph, path: str, params: dict[str, str], *, max_pages: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    after: str | None = None
    for _ in range(max_pages):
        p = dict(params)
        if after:
            p["after"] = after
        resp = g.get(path, p)
        data = resp.get("data")
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict):
                    out.append(row)
        paging = resp.get("paging")
        cursors = paging.get("cursors") if isinstance(paging, dict) else None
        after = cursors.get("after") if isinstance(cursors, dict) else None
        if not after:
            break
    return out


def _find_by_name(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for r in rows:
        if str(r.get("name") or "") == name:
            return r
    return None


def ensure_campaign(
    g: MetaGraph,
    *,
    ad_account_id: str,
    target: dict[str, Any],
    status: str,
    max_pages: int,
) -> str:
    campaign_id = _get_str(target, "campaign_id").strip()
    if campaign_id:
        return campaign_id

    campaign_name = _get_str(target, "campaign_name", "Codex Draft Campaign").strip() or "Codex Draft Campaign"
    reuse_by_name = _get_bool(target, "reuse_by_name", True)
    create_if_missing = _get_bool(target, "create_if_missing", True)
    camp_cfg = _as_dict(target.get("campaign"), "target.campaign")

    if g.dry_run:
        # In dry-run mode we can't list/create; return a stable placeholder.
        return _dry_id("campaign", campaign_name)

    if reuse_by_name:
        rows = _paged_get(
            g,
            f"act_{ad_account_id}/campaigns",
            {"fields": "id,name,status,effective_status", "limit": "50"},
            max_pages=max_pages,
        )
        hit = _find_by_name(rows, campaign_name)
        if hit and isinstance(hit.get("id"), str):
            return hit["id"]

    if not create_if_missing:
        _die(
            "No campaign_id found and campaign_name did not resolve. "
            "Set target.create_if_missing=true or provide target.campaign_id."
        )

    objective = _get_str(camp_cfg, "objective", "TRAFFIC").strip() or "TRAFFIC"
    buying_type = _get_str(camp_cfg, "buying_type", "AUCTION").strip() or "AUCTION"
    special = camp_cfg.get("special_ad_categories", [])
    if not isinstance(special, list):
        special = []

    resp = _retry(
        lambda: g.post_form(
            f"act_{ad_account_id}/campaigns",
            {
                "name": campaign_name,
                "objective": objective,
                "buying_type": buying_type,
                "status": status,
                "special_ad_categories": _json_dumps(special),
            },
        )
    )
    cid = resp.get("id")
    if not isinstance(cid, str) or not cid:
        _die(f"Unexpected campaigns create response (missing id): {resp}")
    return cid


def ensure_adset(
    g: MetaGraph,
    *,
    ad_account_id: str,
    campaign_id: str,
    target: dict[str, Any],
    status: str,
    max_pages: int,
) -> str:
    adset_id = _get_str(target, "adset_id").strip()
    if adset_id:
        return adset_id

    adset_name = _get_str(target, "adset_name", "Codex Draft Ad Set").strip() or "Codex Draft Ad Set"
    reuse_by_name = _get_bool(target, "reuse_by_name", True)
    create_if_missing = _get_bool(target, "create_if_missing", True)
    adset_cfg = _as_dict(target.get("adset"), "target.adset")

    if g.dry_run:
        return _dry_id("adset", f"{campaign_id}:{adset_name}")

    if reuse_by_name:
        rows = _paged_get(
            g,
            f"act_{ad_account_id}/adsets",
            {"fields": "id,name,campaign_id,status,effective_status", "limit": "50"},
            max_pages=max_pages,
        )
        for r in rows:
            if str(r.get("name") or "") == adset_name and str(r.get("campaign_id") or "") == campaign_id:
                rid = r.get("id")
                if isinstance(rid, str) and rid:
                    return rid

    if not create_if_missing:
        _die(
            "No adset_id found and adset_name did not resolve. "
            "Set target.create_if_missing=true or provide target.adset_id."
        )

    # Safe defaults (paused ad set, minimal budget, broad targeting).
    daily_budget = _get_int(adset_cfg, "daily_budget", 100)  # currency minor unit (e.g., cents)
    billing_event = _get_str(adset_cfg, "billing_event", "IMPRESSIONS").strip() or "IMPRESSIONS"
    optimization_goal = _get_str(adset_cfg, "optimization_goal", "LINK_CLICKS").strip() or "LINK_CLICKS"
    destination_type = _get_str(adset_cfg, "destination_type", "WEBSITE").strip() or "WEBSITE"
    targeting = adset_cfg.get(
        "targeting",
        {"geo_locations": {"countries": ["US"]}, "age_min": 18, "age_max": 65},
    )
    if not isinstance(targeting, dict):
        _die("target.adset.targeting must be an object when provided.")

    payload: dict[str, str] = {
        "name": adset_name,
        "campaign_id": campaign_id,
        "status": status,
        "daily_budget": str(daily_budget),
        "billing_event": billing_event,
        "optimization_goal": optimization_goal,
        "destination_type": destination_type,
        "targeting": _json_dumps(targeting),
    }

    resp = _retry(lambda: g.post_form(f"act_{ad_account_id}/adsets", payload))
    aid = resp.get("id")
    if not isinstance(aid, str) or not aid:
        _die(f"Unexpected adsets create response (missing id): {resp}")
    return aid


def upload_image(g: MetaGraph, *, ad_account_id: str, file_path: str) -> str:
    if g.dry_run:
        # Deterministic placeholder so downstream can proceed.
        return _dry_id("imagehash", file_path)
    with open(file_path, "rb") as f:
        content = f.read()
    resp = _retry(
        lambda: g.post_multipart(
            f"act_{ad_account_id}/adimages",
            fields={},
            files={"source": (os.path.basename(file_path), content)},
        )
    )
    # Response shape: {"images":{"<filename>":{"hash":"...","url":"..."}}}
    images = resp.get("images")
    if not isinstance(images, dict) or not images:
        _die(f"Unexpected adimages response: {resp}")
    first = next(iter(images.values()))
    h = first.get("hash")
    if not isinstance(h, str) or not h:
        _die(f"Unexpected adimages response (missing hash): {resp}")
    return h


def upload_video(g: MetaGraph, *, ad_account_id: str, file_path: str) -> str:
    if g.dry_run:
        return _dry_id("video", file_path)
    with open(file_path, "rb") as f:
        content = f.read()
    resp = _retry(
        lambda: g.post_multipart(
            f"act_{ad_account_id}/advideos",
            fields={},
            files={"source": (os.path.basename(file_path), content)},
        )
    )
    vid = resp.get("id")
    if not isinstance(vid, str) or not vid:
        _die(f"Unexpected advideos response (missing id): {resp}")
    return vid


def wait_for_video(g: MetaGraph, *, video_id: str, timeout_s: int = 600, poll_s: int = 5) -> None:
    start = time.time()
    last = None
    while True:
        resp = g.get(video_id, {"fields": "status,permalink_url"})
        status = resp.get("status")
        video_status = None
        processing_progress = None
        if isinstance(status, dict):
            video_status = status.get("video_status") or status.get("processing_phase")
            processing_progress = status.get("processing_progress")
        last = resp

        # Heuristic readiness checks (Meta's exact values vary by API version).
        if isinstance(video_status, str) and video_status.lower() in {"ready", "processed", "complete", "completed"}:
            return
        if isinstance(processing_progress, (int, float)) and processing_progress >= 100:
            return

        if time.time() - start > timeout_s:
            _die(f"Timed out waiting for video processing. Last response: {last}")

        time.sleep(poll_s)


def create_image_creative(
    g: MetaGraph,
    *,
    ad_account_id: str,
    page_id: str,
    name: str,
    image_hash: str,
    destination_url: str,
    primary_text: str,
    headline: str,
    description: str,
    cta_type: str,
) -> str:
    if g.dry_run:
        return _dry_id("creative", name)
    object_story_spec = {
        "page_id": page_id,
        "link_data": {
            "image_hash": image_hash,
            "link": destination_url,
            "message": primary_text,
            "name": headline,
            "description": description,
            "call_to_action": {"type": cta_type, "value": {"link": destination_url}},
        },
    }
    resp = _retry(
        lambda: g.post_form(
            f"act_{ad_account_id}/adcreatives",
            {
                "name": name,
                "object_story_spec": _json_dumps(object_story_spec),
            },
        )
    )
    cid = resp.get("id")
    if not isinstance(cid, str) or not cid:
        _die(f"Unexpected adcreatives response (missing id): {resp}")
    return cid


def create_video_creative(
    g: MetaGraph,
    *,
    ad_account_id: str,
    page_id: str,
    name: str,
    video_id: str,
    destination_url: str,
    primary_text: str,
    headline: str,
    description: str,
    cta_type: str,
) -> str:
    if g.dry_run:
        return _dry_id("creative", name)
    object_story_spec = {
        "page_id": page_id,
        "video_data": {
            "video_id": video_id,
            "message": primary_text,
            "title": headline,
            "link_description": description,
            "call_to_action": {"type": cta_type, "value": {"link": destination_url}},
        },
    }
    resp = _retry(
        lambda: g.post_form(
            f"act_{ad_account_id}/adcreatives",
            {
                "name": name,
                "object_story_spec": _json_dumps(object_story_spec),
            },
        )
    )
    cid = resp.get("id")
    if not isinstance(cid, str) or not cid:
        _die(f"Unexpected adcreatives response (missing id): {resp}")
    return cid


def create_ad(
    g: MetaGraph,
    *,
    ad_account_id: str,
    adset_id: str,
    name: str,
    creative_id: str,
    status: str,
) -> str:
    if g.dry_run:
        return _dry_id("ad", name)
    resp = _retry(
        lambda: g.post_form(
            f"act_{ad_account_id}/ads",
            {
                "name": name,
                "adset_id": adset_id,
                "creative": _json_dumps({"creative_id": creative_id}),
                "status": status,
            },
        )
    )
    aid = resp.get("id")
    if not isinstance(aid, str) or not aid:
        _die(f"Unexpected ads response (missing id): {resp}")
    return aid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="Path to spec JSON.")
    ap.add_argument("--access-token-env", default="META_USER_ACCESS_TOKEN", help="Env var name for access token.")
    ap.add_argument("--app-secret-env", default="META_APP_SECRET", help="Env var name for app secret (optional; for appsecret_proof).")
    ap.add_argument("--dry-run", action="store_true", help="Print requests instead of calling Meta.")
    ap.add_argument("--json-out", default="", help="Write results JSON to this path.")
    ap.add_argument("--video-timeout-s", type=int, default=600, help="Max seconds to wait for video processing.")
    ap.add_argument("--max-pages", type=int, default=20, help="Max pages to scan when resolving by name.")
    args = ap.parse_args()

    token = os.environ.get(args.access_token_env) or ""
    if not token:
        _die(f"Missing access token env var: {args.access_token_env}")

    spec = _read_json(args.spec)
    spec_dir = os.path.dirname(os.path.abspath(args.spec))
    graph_version = str(spec.get("graph_version") or "v24.0")
    ad_account_id = str(spec.get("ad_account_id") or "")
    page_id = str(spec.get("page_id") or "")

    if not ad_account_id or not ad_account_id.isdigit():
        _die("spec.ad_account_id must be the numeric id (no act_ prefix).")
    if not page_id:
        _die("spec.page_id is required.")

    defaults = spec.get("default") or {}
    defaults = _as_dict(defaults, "spec.default")

    ads = spec.get("ads")
    if not isinstance(ads, list) or not ads:
        _die("spec.ads must be a non-empty array.")

    app_secret = os.environ.get(args.app_secret_env) or None
    g = MetaGraph(MetaConfig(graph_version=graph_version, access_token=token, app_secret=app_secret), dry_run=args.dry_run)

    # Safety invariant: never create ACTIVE containers or ads from this tool.
    status = "PAUSED"

    # Resolve placement target (ad set).
    target = _as_dict(spec.get("target") or {}, "spec.target")
    existing_adset_id = _get_str(target, "adset_id").strip()
    if existing_adset_id:
        campaign_id = _get_str(target, "campaign_id").strip() or ""
        adset_id = existing_adset_id
        if not campaign_id and (not g.dry_run):
            # Best-effort: fetch campaign_id for reporting.
            try:
                adset_node = g.get(adset_id, {"fields": "campaign_id,name"})
                cid = adset_node.get("campaign_id")
                if isinstance(cid, str) and cid:
                    campaign_id = cid
            except Exception:
                pass
    else:
        campaign_id = ensure_campaign(
            g,
            ad_account_id=ad_account_id,
            target=target,
            status=status,
            max_pages=max(1, args.max_pages),
        )
        adset_id = ensure_adset(
            g,
            ad_account_id=ad_account_id,
            campaign_id=campaign_id,
            target=target,
            status=status,
            max_pages=max(1, args.max_pages),
        )

    print(f"Using campaign_id={campaign_id or '<unknown>'} adset_id={adset_id} status={status}")

    results: dict[str, Any] = {
        "graph_version": graph_version,
        "ad_account_id": f"act_{ad_account_id}",
        "page_id": page_id,
        "campaign_id": campaign_id,
        "adset_id": adset_id,
        "status": status,
        "ads": [],
    }

    for idx, ad in enumerate(ads, start=1):
        if not isinstance(ad, dict):
            _die(f"ads[{idx}] must be an object.")
        ad_type = str(ad.get("type") or "")
        name = str(ad.get("name") or "").strip()
        file_path = str(ad.get("file") or "").strip()
        if ad_type not in {"image", "video"}:
            _die(f"ads[{idx}].type must be 'image' or 'video'.")
        if not name:
            _die(f"ads[{idx}].name is required.")
        if not file_path:
            _die(f"ads[{idx}].file is required.")
        if not os.path.isabs(file_path):
            file_path = os.path.join(spec_dir, file_path)
        if not os.path.isfile(file_path):
            _die(f"ads[{idx}].file does not exist: {file_path}")

        merged = _merge_defaults(defaults, ad)
        destination_url = str(merged.get("destination_url") or "")
        cta_type = str(merged.get("cta_type") or "LEARN_MORE")
        primary_text = str(merged.get("primary_text") or "")
        headline = str(merged.get("headline") or "")
        description = str(merged.get("description") or "")

        if not destination_url:
            _die(f"ads[{idx}] missing destination_url (or spec.default.destination_url).")
        if not primary_text:
            _die(f"ads[{idx}] missing primary_text (or spec.default.primary_text).")
        if not headline:
            _die(f"ads[{idx}] missing headline (or spec.default.headline).")

        print(f"\n[{idx}/{len(ads)}] {ad_type} :: {name}")

        row: dict[str, Any] = {
            "type": ad_type,
            "name": name,
            "file": file_path,
            "destination_url": destination_url,
            "cta_type": cta_type,
        }

        if ad_type == "image":
            image_hash = upload_image(g, ad_account_id=ad_account_id, file_path=file_path)
            row["image_hash"] = image_hash
            creative_id = create_image_creative(
                g,
                ad_account_id=ad_account_id,
                page_id=page_id,
                name=f"{name} (Creative)",
                image_hash=image_hash,
                destination_url=destination_url,
                primary_text=primary_text,
                headline=headline,
                description=description,
                cta_type=cta_type,
            )
            row["creative_id"] = creative_id
        else:
            video_id = upload_video(g, ad_account_id=ad_account_id, file_path=file_path)
            row["video_id"] = video_id
            if not args.dry_run:
                wait_for_video(g, video_id=video_id, timeout_s=args.video_timeout_s)
            creative_id = create_video_creative(
                g,
                ad_account_id=ad_account_id,
                page_id=page_id,
                name=f"{name} (Creative)",
                video_id=video_id,
                destination_url=destination_url,
                primary_text=primary_text,
                headline=headline,
                description=description,
                cta_type=cta_type,
            )
            row["creative_id"] = creative_id

        ad_id = create_ad(
            g,
            ad_account_id=ad_account_id,
            adset_id=adset_id,
            name=name,
            creative_id=str(row["creative_id"]),
            status=status,
        )
        row["ad_id"] = ad_id

        print(json.dumps(row, indent=2, sort_keys=True))
        results["ads"].append(row)

    if args.json_out:
        out_path = args.json_out
        if not os.path.isabs(out_path):
            out_path = os.path.join(os.getcwd(), out_path)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, sort_keys=True)
            f.write("\n")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
