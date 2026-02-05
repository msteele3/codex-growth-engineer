#!/usr/bin/env python3
"""
End-to-end workflow:
1) Scrape + bundle competitor ads (Meta Ads Library) via track_ads.py
2) Generate a vertical Sora video (720x1280 by default) using product brief + ad analysis
3) Upload the generated video to Meta Ads Manager as PAUSED draft ad via meta_ads_draft_uploader.py

Design goals:
- Run in parts: each stage can be skipped; existing artifacts are reused.
- Fail fast if product brief is missing required fields (no side effects).
- Default outputs to vertical paid-social creative sizes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
from typing import Any


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        _die(f"Failed to read JSON: {path}\n{e}")
        raise


def _get(d: dict[str, Any], path: str, *, required: bool = True) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            if required:
                _die(f"Missing required product brief field: {path}")
            return None
        cur = cur[part]
    return cur


def _ensure_list(x: Any, what: str) -> list[str]:
    if not isinstance(x, list) or not all(isinstance(i, str) and i.strip() for i in x):
        _die(f"{what} must be a non-empty array of strings.")
    return [i.strip() for i in x]


def _repo_root() -> pathlib.Path:
    # <repo>/skills/meta-ads-library-tracker/scripts/e2e_workflow.py
    return pathlib.Path(__file__).resolve().parents[3]


def _strip_quotes(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        return v[1:-1]
    return v


def _load_dotenv_file(path: pathlib.Path) -> dict[str, str]:
    """
    Minimal .env parser:
    - supports KEY=VALUE and `export KEY=VALUE`
    - ignores blank lines and comments starting with #
    - strips surrounding single/double quotes from VALUE
    """
    out: dict[str, str] = {}
    if not path.exists():
        return out
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return out
    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[len("export ") :].strip()
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = _strip_quotes(v.strip())
        if not k:
            continue
        out[k] = v
    return out


def _maybe_load_dotenv(mode: str, *, repo: pathlib.Path, override: bool) -> pathlib.Path | None:
    """
    Loads env vars from a .env file into os.environ.
    - mode="off": do nothing
    - mode="auto": try <repo_root>/.env then <cwd>/.env
    - otherwise: treat as a path to a .env file

    By default, this only sets missing/empty env vars. If override=True, values from
    the .env file replace already-set env vars. This is important for automations,
    where stale/bad keys can be present in the runner environment.
    """
    m = (mode or "").strip() or "auto"
    if m.lower() == "off":
        return None
    candidates: list[pathlib.Path]
    if m.lower() == "auto":
        candidates = [repo / ".env", pathlib.Path.cwd() / ".env"]
    else:
        candidates = [pathlib.Path(m).expanduser()]
    for p in candidates:
        if not p.is_file():
            continue
        loaded = _load_dotenv_file(p)
        for k, v in loaded.items():
            if not k:
                continue
            if override:
                os.environ[k] = v
            else:
                if k not in os.environ or (os.environ.get(k) or "") == "":
                    os.environ[k] = v
        return p
    return None


def _default_sora_cli() -> pathlib.Path:
    codex_home = pathlib.Path(os.environ.get("CODEX_HOME") or pathlib.Path.home() / ".codex")
    return codex_home / "skills" / "sora" / "scripts" / "sora.py"


def _run(cmd: list[str], *, cwd: pathlib.Path, env: dict[str, str] | None = None) -> None:
    p = subprocess.run(cmd, cwd=str(cwd), env=env, stdout=sys.stdout, stderr=sys.stderr)
    if p.returncode != 0:
        _die(f"Command failed ({p.returncode}): {' '.join(cmd)}", code=p.returncode)


def _render_sora_prompt(*, brief: dict[str, Any], ad_analysis: dict[str, Any]) -> str:
    product_name = str(_get(brief, "product_name"))
    colors = _get(brief, "brand.colors")
    primary = str(_get(colors, "primary"))
    primary_fg = str(_get(colors, "primary_foreground"))
    bg_dark = str(_get(colors, "background_dark"))
    surface_light = str(_get(colors, "surface_light"))

    features = _ensure_list(_get(brief, "claims.features"), "claims.features")
    outcomes = _ensure_list(_get(brief, "claims.outcomes"), "claims.outcomes")
    forbidden = _ensure_list(_get(brief, "claims.forbidden"), "claims.forbidden")

    hook = str(ad_analysis.get("hook") or "").strip()
    summary = str(ad_analysis.get("ad_summary") or "").strip()

    # Important: avoid therapy/medical language while still using the competitor-style "contrarian" hook.
    hook_rewrite = "I'm not another chatbot that forgets you. I remember what matters."

    proof_points = [
        "Remembers important details, so conversations build over time",
        "Text, voice, and video calls when you want to feel closer",
        "A journal that captures moments worth remembering",
    ]

    prompt = f"""\
Use case: paid social (vertical video ad)
Primary request: Create an 8s vertical ad for "{product_name}" inspired by a top competitor ad's pacing: bold high-contrast captions, quick beats, and a product UI reveal. Use original visuals and copy.

Competitor inspiration (do not copy visuals): {summary or '(summary unavailable)'}
Competitor hook pattern: {hook or '(hook unavailable)'}
Our hook (verbatim): "{hook_rewrite}"

Scene/background: Dark premium gradient background (base {bg_dark}) with subtle grain and faint glow accents. UI panels float with parallax.
Subject: Original abstract non-human chat-avatar (no real person, no face realism). Message bubbles + a phone UI mock in a clean frame.
Action: Rapid caption beats + UI cuts. Show the app remembering a small detail and drafting a message. End card with brand name + CTA.
Camera: Locked-off with punch-in zooms on UI; quick jump cuts; subtle parallax; clean motion.
Lighting/mood: Premium, moody, confident, reassuring.
Color palette: {bg_dark} (background), {primary} (accent), {primary_fg} (soft highlight), {surface_light} (UI surface).
Style/format: minimal motion-graphics + UI mock; bold kinetic typography; high readability; social ad pacing.

Timing/beats:
- 0.0-1.0s: Big caption hook (use the verbatim hook). Quick punch-in.
- 1.0-3.0s: 2 proof points as bold captions over UI snippets.
- 3.0-6.0s: Show "{product_name}" remembering an important detail + drafting a message; show a journal entry card briefly.
- 6.0-8.0s: End card with "{product_name}" and a clear Download CTA.

On-screen proof points (choose 2, keep very short):
- {proof_points[0]}
- {proof_points[1]}
- {proof_points[2]}

Product feature anchors (do not over-claim):
- {features[0]}
- {features[1] if len(features) > 1 else features[0]}
- {features[2] if len(features) > 2 else features[0]}

Desired outcomes:
- {outcomes[0]}
- {outcomes[1] if len(outcomes) > 1 else outcomes[0]}

Constraints:
- No real people; no faces; no copyrighted characters; no logos besides the text "{product_name}".
- Keep all copy PG-13.
- Avoid: {", ".join(forbidden)}

Audio: subtle modern synth pulse + soft whooshes (no recognizable song).
Text (verbatim): "{product_name}"
Avoid: unreadable UI text, messy artifacts, excessive motion blur, jitter.
"""
    return prompt.strip() + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls-file", required=True, help="Text file with one Meta Ads Library advertiser URL per line.")
    ap.add_argument("--out-dir", default="data/meta-ads-library", help="Output directory.")
    ap.add_argument("--product-brief", default="data/meta-ads-library/product_brief.json", help="Path to product brief JSON.")
    ap.add_argument("--top-n", type=int, default=5, help="How many competitor ads to consider.")
    ap.add_argument("--pick-index", type=int, default=0, help="Pick which ad from snapshot top_ads to use (0-based).")
    ap.add_argument("--vision-model", default="gpt-4.1", help="Model used by track_ads.py for analysis.")
    ap.add_argument(
        "--dotenv",
        default="auto",
        help="Load env vars from a .env file. Use 'auto' (default), 'off', or a path.",
    )
    ap.add_argument(
        "--dotenv-override",
        action="store_true",
        help="If set, .env values override already-set env vars (useful for automations).",
    )

    ap.add_argument("--skip-track", action="store_true", help="Skip running track_ads.py (use existing snapshot).")
    ap.add_argument("--analysis-only", action="store_true", help="If set, run track_ads.py in analysis-only mode.")
    ap.add_argument("--reanalyze-empty", action="store_true", help="Re-run analysis when analysis.json is missing/empty/invalid.")

    ap.add_argument("--skip-sora", action="store_true", help="Skip Sora generation.")
    ap.add_argument("--sora-cli", default="", help="Path to sora.py (defaults to $CODEX_HOME/skills/sora/scripts/sora.py).")
    ap.add_argument("--sora-model", default="sora-2", help="Sora model.")
    ap.add_argument("--sora-size", default="720x1280", help="Sora output size WxH (default: 720x1280).")
    ap.add_argument("--sora-seconds", default="8", help="Sora seconds enum: 4/8/12.")
    ap.add_argument("--sora-out", default="", help="Write generated mp4 to this path (default under out-dir).")

    ap.add_argument("--skip-upload", action="store_true", help="Skip Meta upload.")
    ap.add_argument("--upload-dry-run", action="store_true", help="Run meta uploader with --dry-run.")
    ap.add_argument("--upload", action="store_true", help="Run Meta upload (PAUSED draft).")
    args = ap.parse_args(argv)

    repo = _repo_root()
    out_dir = pathlib.Path(args.out_dir)
    brief_path = pathlib.Path(args.product_brief)

    _maybe_load_dotenv(args.dotenv, repo=repo, override=bool(args.dotenv_override))

    if not brief_path.exists():
        _die(
            "Missing product brief JSON. This workflow requires product context up front.\n"
            f"Expected: {brief_path}\n"
            f"Example: {repo / 'skills/meta-ads-library-tracker/references/product_brief.example.json'}"
        )

    brief = _load_json(brief_path)
    # Validate required fields; fail immediately if missing.
    _get(brief, "product_name")
    _get(brief, "brand.colors.primary")
    _get(brief, "brand.colors.primary_foreground")
    _get(brief, "brand.colors.background_dark")
    _get(brief, "brand.colors.surface_light")
    _ensure_list(_get(brief, "claims.features"), "claims.features")
    _ensure_list(_get(brief, "claims.outcomes"), "claims.outcomes")
    _ensure_list(_get(brief, "claims.forbidden"), "claims.forbidden")
    _get(brief, "cta.destination_url")
    _get(brief, "cta.headline")
    _get(brief, "cta.primary_text")
    _get(brief, "meta.ad_account_id_env")
    _get(brief, "meta.page_id_env")
    _get(brief, "meta.access_token_env")
    _get(brief, "meta.graph_version_env")

    # Step 1: track ads (optional).
    if not args.skip_track:
        track_cmd = [
            sys.executable,
            str(repo / "skills/meta-ads-library-tracker/scripts/track_ads.py"),
            "--urls-file",
            args.urls_file,
            "--out-dir",
            str(out_dir),
            "--top-n",
            str(args.top_n),
            "--browser-channel",
            "",
            "--allow-channel-fallback",
            "--max-video-seconds",
            "12",
            "--fps",
            "1",
            "--vision-model",
            args.vision_model,
            "--dotenv",
            "auto",
            "--dotenv-override",
        ]
        if args.analysis_only:
            track_cmd.append("--analysis-only")
        if args.reanalyze_empty:
            track_cmd.append("--reanalyze-empty")
        _run(track_cmd, cwd=repo)

    # Load snapshot + pick ad.
    urls_file = pathlib.Path(args.urls_file)
    urls = [ln.strip() for ln in urls_file.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not urls:
        _die("No URLs found in --urls-file.")
    # This keying matches track_ads.py: uses view_all_page_id as key when present.
    # We'll use the first URL for now.
    import re as _re
    import urllib.parse as _up

    q = _up.parse_qs(_up.urlparse(urls[0]).query)
    page_id = (q.get("view_all_page_id") or [""])[0]
    advertiser_key = page_id if _re.fullmatch(r"\\d+", page_id or "") else page_id or "advertiser"

    snap = _load_json(out_dir / "snapshots" / advertiser_key / "latest.json")
    top_ads = snap.get("top_ads") or []
    if not isinstance(top_ads, list) or not top_ads:
        _die("No top_ads found in snapshot; run track step first.")

    if args.pick_index < 0 or args.pick_index >= len(top_ads):
        _die(f"--pick-index out of range (0..{len(top_ads)-1}).")

    picked = top_ads[args.pick_index]
    if not isinstance(picked, dict):
        _die("Snapshot top_ads entry is not an object.")

    ad_id = str(picked.get("ad_archive_id") or "").strip()
    if not ad_id:
        _die("Picked ad is missing ad_archive_id.")

    bundle_dir = out_dir / (picked.get("bundle_dir") or f"creatives/{advertiser_key}/{ad_id}")
    analysis_path = bundle_dir / "analysis.json"
    analysis = _load_json(analysis_path)

    # Step 2: Sora generation.
    sora_out = pathlib.Path(args.sora_out) if args.sora_out else out_dir / "sora" / f"{dt.date.today().isoformat()}_{ad_id}_{args.sora_size}.mp4"
    sora_out.parent.mkdir(parents=True, exist_ok=True)
    prompt_path = sora_out.with_suffix(".prompt.txt")
    prompt_path.write_text(_render_sora_prompt(brief=brief, ad_analysis=analysis), encoding="utf-8")

    if not args.skip_sora:
        sora_cli = pathlib.Path(args.sora_cli) if args.sora_cli else _default_sora_cli()
        if not sora_cli.exists():
            _die(f"Sora CLI not found: {sora_cli}")
        sora_cmd = [
            sys.executable,
            str(sora_cli),
            "create-and-poll",
            "--model",
            args.sora_model,
            "--size",
            args.sora_size,
            "--seconds",
            str(args.sora_seconds),
            "--prompt-file",
            str(prompt_path),
            "--no-augment",
            "--download",
            "--variant",
            "video",
            # Allows reruns on the same day/ad_id without failing when outputs already exist.
            "--force",
            "--out",
            str(sora_out),
            "--json-out",
            str(sora_out.with_suffix(".job.json")),
        ]
        _run(sora_cmd, cwd=repo)

    # Step 3: Meta upload.
    if args.upload and not args.skip_upload:
        meta = _get(brief, "meta")
        ad_account_id_env = str(_get(meta, "ad_account_id_env"))
        page_id_env = str(_get(meta, "page_id_env"))
        graph_version_env = str(_get(meta, "graph_version_env"))

        ad_account_id = (os.environ.get(ad_account_id_env) or "").strip()
        page_id_val = (os.environ.get(page_id_env) or "").strip()
        graph_version = (os.environ.get(graph_version_env) or "v24.0").strip() or "v24.0"
        if not ad_account_id or not ad_account_id.isdigit():
            _die(f"Missing/invalid env {ad_account_id_env} (must be numeric, no act_ prefix).")
        if not page_id_val:
            _die(f"Missing env {page_id_env}.")

        cta = _get(brief, "cta")
        destination_url = str(_get(cta, "destination_url"))
        headline = str(_get(cta, "headline"))
        primary_text = str(_get(cta, "primary_text"))
        description = str(cta.get("description") or "")

        spec_dir = out_dir / "meta-upload"
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec_path = spec_dir / f"spec_{dt.date.today().isoformat()}_{ad_id}.json"
        results_path = spec_dir / f"results_{dt.date.today().isoformat()}_{ad_id}.json"

        spec = {
            "graph_version": graph_version,
            "ad_account_id": ad_account_id,
            "page_id": page_id_val,
            "default": {
                "destination_url": destination_url,
                "primary_text": primary_text,
                "headline": headline,
                "description": description,
            },
            "ads": [
                {
                    "type": "video",
                    "name": f"{brief.get('product_name')} - Sora {ad_id}",
                    "file": str(sora_out.resolve()),
                }
            ],
        }
        spec_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        uploader = repo / "skills/meta-ads-draft-uploader/scripts/meta_ads_draft_uploader.py"
        upload_cmd = [sys.executable, str(uploader), "--spec", str(spec_path), "--json-out", str(results_path)]
        if args.upload_dry_run:
            upload_cmd.append("--dry-run")
        _run(upload_cmd, cwd=repo)

        print(f"Wrote Meta spec: {spec_path}")
        print(f"Wrote Meta results: {results_path}")

    print(f"Sora prompt: {prompt_path}")
    print(f"Sora video: {sora_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
