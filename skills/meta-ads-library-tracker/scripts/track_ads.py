#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import textwrap
import time
import urllib.parse
from typing import Any, Iterable, Literal


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _repo_root() -> pathlib.Path:
    # This script lives at: <repo>/skills/meta-ads-library-tracker/scripts/track_ads.py
    # So repo root is 3 parents up from scripts/.
    return pathlib.Path(__file__).resolve().parents[3]


def _load_dotenv_file(path: pathlib.Path) -> dict[str, str]:
    """
    Minimal .env parser:
    - supports KEY=VALUE
    - strips surrounding single/double quotes
    - ignores blank lines and comments
    """
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        env[k] = v
    return env


def _maybe_load_dotenv(mode: str, *, override: bool) -> None:
    """
    Loads env vars from a .env file into os.environ.
    - mode="off": do nothing
    - mode="auto": try repo root .env, then cwd .env
    - otherwise: treat as a path to a .env file
    If override=True, values from .env replace existing os.environ values.
    """
    m = (mode or "").strip() or "auto"
    if m == "off":
        return

    candidates: list[pathlib.Path]
    if m == "auto":
        candidates = [_repo_root() / ".env", pathlib.Path.cwd() / ".env"]
    else:
        candidates = [pathlib.Path(m)]

    for p in candidates:
        loaded = _load_dotenv_file(p)
        if not loaded:
            continue
        for k, v in loaded.items():
            if override or (k not in os.environ) or ((os.environ.get(k) or "") == ""):
                os.environ[k] = v
        return


def _today_local() -> dt.date:
    return dt.date.today()


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
    return s or "advertiser"


def _parse_view_all_page_id(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(parsed.query)
    page_ids = q.get("view_all_page_id") or []
    if not page_ids:
        return None
    page_id = (page_ids[0] or "").strip()
    return page_id if re.fullmatch(r"\d+", page_id) else None


def _parse_date_mdy(s: str) -> dt.date | None:
    s = (s or "").strip()
    if not s:
        return None
    # Most common format: "Jan 2, 2025" / "January 2, 2025"
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _ensure_ffmpeg() -> None:
    if subprocess.call(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        raise RuntimeError("ffmpeg not found on PATH; install ffmpeg to extract frames/audio")


def _run_ffmpeg(args: list[str]) -> None:
    proc = subprocess.run(["ffmpeg", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-25:])
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}). Tail:\n{tail}")


def _extract_frames(video_path: pathlib.Path, frames_dir: pathlib.Path, *, fps: int, max_seconds: int) -> list[pathlib.Path]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    out_pattern = str(frames_dir / "frame_%05d.jpg")
    # Scale down a bit to keep analysis payloads reasonable; keep aspect ratio.
    vf = f"fps={fps},scale=720:-1"
    _run_ffmpeg(["-y", "-i", str(video_path), "-t", str(max_seconds), "-vf", vf, out_pattern])
    return sorted(frames_dir.glob("frame_*.jpg"))


def _extract_audio(video_path: pathlib.Path, audio_path: pathlib.Path, *, max_seconds: int) -> pathlib.Path:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            "-y",
            "-i",
            str(video_path),
            "-t",
            str(max_seconds),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-b:a",
            "128k",
            str(audio_path),
        ]
    )
    return audio_path


def _downscale_for_llm(src: pathlib.Path, dst: pathlib.Path, *, max_side_px: int = 768, jpeg_quality: int = 70) -> pathlib.Path:
    from PIL import Image

    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        scale = min(1.0, float(max_side_px) / float(max(w, h)))
        if scale < 1.0:
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        im.save(dst, format="JPEG", quality=jpeg_quality, optimize=True)
    return dst


def _dominant_colors_hex(src: pathlib.Path, *, n: int = 6) -> list[str]:
    # Fast-ish heuristic: quantize down to n colors and return hex.
    from PIL import Image

    with Image.open(src) as im:
        im = im.convert("RGB")
        im = im.resize((256, 256))
        q = im.quantize(colors=max(2, n))
        palette = q.getpalette() or []
        counts = sorted(q.getcolors() or [], reverse=True)
        out: list[str] = []
        for _, idx in counts[:n]:
            base = idx * 3
            if base + 2 >= len(palette):
                continue
            r, g, b = palette[base], palette[base + 1], palette[base + 2]
            out.append(f"#{r:02x}{g:02x}{b:02x}")
        # De-dupe while preserving order.
        dedup: list[str] = []
        seen: set[str] = set()
        for c in out:
            if c in seen:
                continue
            seen.add(c)
            dedup.append(c)
        return dedup


def _b64_data_url(image_path: pathlib.Path) -> dict[str, Any]:
    ext = image_path.suffix.lower()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _load_openai_client():
    try:
        from openai import OpenAI
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Missing OpenAI Python package. Install with: python3 -m pip install --upgrade openai"
        ) from e
    return OpenAI()


def _transcribe_audio(*, audio_path: pathlib.Path, model: str) -> str:
    client = _load_openai_client()
    with audio_path.open("rb") as f:
        out = client.audio.transcriptions.create(file=f, model=model)
    # The SDK may return a string or an object depending on response_format.
    if isinstance(out, str):
        return out.strip()
    text = getattr(out, "text", None)
    if isinstance(text, str):
        return text.strip()
    return str(out).strip()


def _chat_json(
    *,
    model: str,
    system: str | None,
    user_content: list[dict[str, Any]],
    max_tokens: int,
) -> tuple[dict[str, Any] | None, str]:
    client = _load_openai_client()
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_content})

    def _parse_text(s: str) -> tuple[dict[str, Any] | None, str]:
        s = (s or "").strip()
        if not s:
            return None, ""
        try:
            return json.loads(s), s
        except Exception:
            # Try to salvage a JSON object embedded in a longer response.
            m = re.search(r"\{.*\}", s, re.S)
            if m:
                try:
                    return json.loads(m.group(0)), s
                except Exception:
                    pass
            return None, s

    text = ""
    # Chat Completions: works for text-only content, but some models return empty
    # content when vision parts are present. We'll fall back to Responses if needed.
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception:
        # We'll fall back below.
        text = ""

    if not text:
        # Responses API supports multimodal reliably (input_text/input_image).
        input_parts: list[dict[str, Any]] = []
        for part in user_content:
            t = part.get("type")
            if t == "text":
                input_parts.append({"type": "input_text", "text": str(part.get("text") or "")})
            elif t == "image_url":
                url = ((part.get("image_url") or {}).get("url") or "").strip()
                if url:
                    input_parts.append({"type": "input_image", "image_url": url})
            else:
                # Unknown part type; ignore.
                continue

        r = client.responses.create(
            model=model,
            instructions=system or None,
            input=[{"role": "user", "content": input_parts}],
            max_output_tokens=max_tokens,
            # Enforce a single JSON object output for resilience.
            text={"format": {"type": "json_object"}},
        )
        text = (getattr(r, "output_text", "") or "").strip()

    parsed, raw = _parse_text(text)
    return parsed, raw


def _print_stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclasses.dataclass(frozen=True)
class AdCandidate:
    ad_archive_id: str
    started_running: dt.date
    started_running_text: str
    days_running: int
    source_url: str


@dataclasses.dataclass(frozen=True)
class AdDetails:
    ad_archive_id: str
    detail_url: str
    page_title: str
    messages: list[str]
    headlines: list[str]
    descriptions: list[str]
    image_urls: list[str]
    video_urls: list[str]


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Playwright is required to scrape Meta Ads Library.\n\n"
            "Install:\n"
            "  python3 -m pip install --upgrade playwright\n"
            "  python3 -m playwright install chromium\n"
        ) from e


def _collect_ad_candidates_from_page(page) -> list[dict[str, Any]]:
    # Preferred path: Ads Library often embeds Relay-prefetched JSON in
    # <script type="application/json"> blobs. Extracting from those is far
    # more reliable than looking for ad links in the rendered DOM.
    js = r"""
() => {
  const out = new Map();

  const walk = (obj, fn) => {
    const stack = [obj];
    const seen = new Set();
    while (stack.length) {
      const cur = stack.pop();
      if (!cur || typeof cur !== 'object') continue;
      if (seen.has(cur)) continue;
      seen.add(cur);

      try { fn(cur); } catch (e) {}

      if (Array.isArray(cur)) {
        for (const v of cur) stack.push(v);
      } else {
        for (const k of Object.keys(cur)) stack.push(cur[k]);
      }
    }
  };

  const scripts = Array.from(document.querySelectorAll('script[type=\"application/json\"]'));
  for (const s of scripts) {
    const txt = s.textContent || '';
    if (!txt.includes('ad_library_main') || !txt.includes('search_results_connection')) continue;
    let root = null;
    try { root = JSON.parse(txt); } catch (e) { continue; }

    walk(root, (node) => {
      const main = node && node.ad_library_main;
      const conn = main && main.search_results_connection;
      const edges = conn && conn.edges;
      if (!Array.isArray(edges)) return;

      for (const edge of edges) {
        const n = edge && edge.node;
        const collated = n && n.collated_results;
        if (!Array.isArray(collated)) continue;
        for (const cr of collated) {
          const adId = cr && cr.ad_archive_id;
          if (!adId) continue;
          const key = String(adId);
          if (out.has(key)) continue;
          out.set(key, {
            ad_archive_id: key,
            start_date: cr.start_date ?? null,
            end_date: cr.end_date ?? null,
            is_active: cr.is_active ?? null,
          });
        }
      }
    });
  }

  // Fallback: look for ad ids in links. This often fails for Ads Library
  // because details links may be handled by JS and not rendered as hrefs.
  if (out.size === 0) {
    const anchors = Array.from(document.querySelectorAll('a[href]'));
    for (const a of anchors) {
      const href = a.getAttribute('href') || '';
      const m = href.match(/[?&]id=(\d+)/);
      if (!m) continue;
      const adId = m[1];
      if (out.has(adId)) continue;
      out.set(adId, { ad_archive_id: String(adId), start_date: null, end_date: null, is_active: null });
    }
  }

  return Array.from(out.values());
}
"""
    return page.evaluate(js)


def _dismiss_known_modals(page) -> None:
    # Best-effort modal dismissal; safe to no-op when selectors don't exist.
    candidates = [
        "text=/Accept all cookies/i",
        "text=/Allow all cookies/i",
        "text=/Only allow essential cookies/i",
        "text=/Accept/i",
        "text=/Agree/i",
        "text=/Close/i",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if loc and loc.is_visible():
                loc.click(timeout=500)
                time.sleep(0.2)
        except Exception:
            pass


def scrape_advertiser_active_ads(
    *,
    page,
    advertiser_url: str,
    top_n: int,
    max_scrolls: int,
    stall_iters: int,
    scroll_px: int,
    timeout_s: int,
    debug_dir: pathlib.Path | None,
) -> list[AdCandidate]:
    page.goto(advertiser_url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(debug_dir / "advertiser_initial.png"), full_page=True)
        except Exception:
            pass
        try:
            (debug_dir / "advertiser_initial.html").write_text(page.content(), encoding="utf-8")
        except Exception:
            pass
    _dismiss_known_modals(page)
    # Wait a bit for results; Ads Library is slow and network-variable.
    page.wait_for_timeout(2000)

    seen: set[str] = set()
    with_date: dict[str, dt.date] = {}
    stall = 0
    for i in range(max_scrolls):
        _dismiss_known_modals(page)
        try:
            raw = _collect_ad_candidates_from_page(page)
        except Exception:
            raw = []
        if debug_dir and (i in (0, 1, 2) or i % 5 == 0):
            try:
                sample = []
                for item in (raw or [])[:200]:
                    sample.append(
                        {
                            "ad_archive_id": item.get("ad_archive_id"),
                            "start_date": item.get("start_date"),
                            "end_date": item.get("end_date"),
                            "is_active": item.get("is_active"),
                        }
                    )
                _json_dump(debug_dir / f"extracted_{i:02d}.json", {"count": len(raw or []), "sample": sample})
            except Exception:
                pass
        new_any = False
        for item in raw or []:
            ad_id = str(item.get("ad_archive_id") or "").strip()
            start_date = item.get("start_date")
            is_active = item.get("is_active")
            if not ad_id:
                continue
            if is_active is False:
                continue

            if ad_id not in seen:
                seen.add(ad_id)
                new_any = True

            if start_date is not None and ad_id not in with_date:
                try:
                    ts = int(start_date)
                except Exception:
                    ts = 0
                if ts > 0:
                    d = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()
                    with_date[ad_id] = d
                    new_any = True

        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / f"scroll_{i:02d}.txt").write_text(
                f"seen={len(seen)} with_date={len(with_date)}\n",
                encoding="utf-8",
            )

        if not new_any:
            stall += 1
        else:
            stall = 0
        if stall >= stall_iters:
            break

        # Scroll near the bottom to trigger infinite-load of more results.
        # (Scrolling by a fixed amount can stall too early if the list is long.)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        page.wait_for_timeout(1600)

    if debug_dir:
        try:
            page.screenshot(path=str(debug_dir / "advertiser_final.png"), full_page=True)
        except Exception:
            pass
        try:
            (debug_dir / "advertiser_final.html").write_text(page.content(), encoding="utf-8")
        except Exception:
            pass

    # Build candidates ranked by days running (desc).
    today = _today_local()
    candidates: list[AdCandidate] = []
    for ad_id, started in with_date.items():
        days = (today - started).days
        started_text = started.isoformat()
        candidates.append(
            AdCandidate(
                ad_archive_id=ad_id,
                started_running=started,
                started_running_text=started_text,
                days_running=days,
                source_url=advertiser_url,
            )
        )
    candidates.sort(key=lambda c: c.days_running, reverse=True)
    return candidates[: max(0, top_n)]


def _extract_ad_details_from_detail_page(page) -> dict[str, Any]:
    js = r"""
() => {
  const uniq = (arr) => {
    const out = [];
    const seen = new Set();
    for (const x of arr) {
      if (!x) continue;
      if (seen.has(x)) continue;
      seen.add(x);
      out.push(x);
    }
    return out;
  };

  const imgEls = Array.from(document.querySelectorAll('img'));
  const images = imgEls
    .map(img => ({
      url: img.currentSrc || img.src || '',
      w: img.naturalWidth || 0,
      h: img.naturalHeight || 0,
    }))
    .filter(x => x.url && !x.url.startsWith('data:') && x.w >= 200 && x.h >= 200)
    .map(x => x.url);

  const vidEls = Array.from(document.querySelectorAll('video'));
  const videos = [];
  for (const v of vidEls) {
    if (v.currentSrc) videos.push(v.currentSrc);
    if (v.src) videos.push(v.src);
    const sources = Array.from(v.querySelectorAll('source')).map(s => s.src).filter(Boolean);
    for (const s of sources) videos.push(s);
  }

  const pickText = (selector) =>
    uniq(Array.from(document.querySelectorAll(selector)).map(el => (el.innerText || '').trim()).filter(Boolean));

  const messages = pickText('[data-ad-preview="message"]');
  const headlines = pickText('[data-ad-preview="title"]');
  const descriptions = pickText('[data-ad-preview="description"]');

  return {
    page_title: document.title || '',
    image_urls: uniq(images),
    video_urls: uniq(videos.filter(u => u && !u.startsWith('blob:'))),
    messages,
    headlines,
    descriptions,
  };
}
"""
    return page.evaluate(js)


def scrape_ad_details(*, context, ad_archive_id: str, timeout_s: int) -> AdDetails:
    detail_url = f"https://www.facebook.com/ads/library/?id={urllib.parse.quote(ad_archive_id)}"
    page = context.new_page()
    try:
        page.goto(detail_url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
        _dismiss_known_modals(page)
        page.wait_for_timeout(1500)
        _dismiss_known_modals(page)

        data = _extract_ad_details_from_detail_page(page)
        return AdDetails(
            ad_archive_id=ad_archive_id,
            detail_url=detail_url,
            page_title=str(data.get("page_title") or ""),
            messages=[str(x) for x in (data.get("messages") or []) if str(x).strip()],
            headlines=[str(x) for x in (data.get("headlines") or []) if str(x).strip()],
            descriptions=[str(x) for x in (data.get("descriptions") or []) if str(x).strip()],
            image_urls=[str(x) for x in (data.get("image_urls") or []) if str(x).strip()],
            video_urls=[str(x) for x in (data.get("video_urls") or []) if str(x).strip()],
        )
    finally:
        page.close()


def _load_snapshot_ads(
    *, snapshots_dir: pathlib.Path, advertiser_key: str
) -> list[dict[str, Any]] | None:
    """
    Reads snapshots/<advertiser_key>/latest.json if present and returns its top_ads list.
    Used to support running the script in parts (download first, analyze later).
    """
    p = snapshots_dir / advertiser_key / "latest.json"
    if not p.exists():
        return None
    d = _load_json(p) or {}
    ads = d.get("top_ads")
    if isinstance(ads, list):
        return [x for x in ads if isinstance(x, dict)]
    return None


def _guess_ext_from_url(url: str, *, default: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or ""
    ext = pathlib.Path(path).suffix.lower()
    if ext and re.fullmatch(r"\.[a-z0-9]{1,5}", ext):
        return ext
    return default


def _download_via_playwright_request(*, request_ctx, url: str, out_path: pathlib.Path, timeout_s: int) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = request_ctx.get(url, timeout=timeout_s * 1000)
        if not resp or not resp.ok:
            return False
        body = resp.body()
        if not body:
            return False
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(out_path)
        return True
    except Exception:
        return False


def _download_hls_with_ffmpeg(url: str, out_path: pathlib.Path, *, max_seconds: int, user_agent: str) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-y",
        "-user_agent",
        user_agent,
        "-i",
        url,
        "-t",
        str(max_seconds),
        "-c",
        "copy",
        str(out_path),
    ]
    try:
        _run_ffmpeg(args)
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def _write_text(path: pathlib.Path, s: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(s, encoding="utf-8")
    tmp.replace(path)


def _as_relpath(path: pathlib.Path, base: pathlib.Path) -> str:
    try:
        return str(path.relative_to(base))
    except Exception:
        return str(path)


def _analysis_needs_rerun(obj: dict[str, Any] | None) -> bool:
    if not obj:
        return True
    err = (obj.get("error") or "").strip() if isinstance(obj.get("error"), str) else ""
    if err:
        return True
    raw = (obj.get("raw_text") or "") if isinstance(obj.get("raw_text"), str) else ""
    # Empty raw text is effectively "no analysis" for our purposes.
    if raw.strip() == "" and set(obj.keys()) <= {"raw_text"}:
        return True
    # If we only have raw_text, ensure it's a valid JSON object; otherwise rerun.
    if set(obj.keys()) == {"raw_text"}:
        if raw.strip() == "":
            return True
        try:
            parsed = json.loads(raw)
            return not isinstance(parsed, dict)
        except Exception:
            return True
    return False


def _load_json(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def analyze_image_ad(
    *,
    model: str,
    ad_meta: dict[str, Any],
    image_paths: list[pathlib.Path],
    ad_text: str,
    palette_by_image: dict[str, list[str]],
    max_tokens: int,
) -> dict[str, Any]:
    images_for_llm: list[pathlib.Path] = []
    for img in image_paths[:5]:
        images_for_llm.append(img)

    user_parts: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": textwrap.dedent(
                f"""
                You are analyzing a Meta Ads Library IMAGE ad for a creative inspiration library.

                Return a single JSON object with these keys:
                - ad_summary: string (1-2 sentences)
                - hook: string (the hook line or visual hook; be specific)
                - primary_message: string
                - visual_description: string (what is shown)
                - on_screen_text: list[string] (best-effort)
                - style: object with keys: color_palette (list[string hex]), typography, layout, imagery_style, brand_vibes
                - cta_offer: object with keys: cta, offer, urgency, audience
                - inspiration_notes: list[string] (actionable tactics)

                Context:
                - ad_meta: {json.dumps(ad_meta, ensure_ascii=True)}
                - extracted_text: {json.dumps(ad_text[:2000], ensure_ascii=True)}
                - computed_palettes_by_image: {json.dumps(palette_by_image, ensure_ascii=True)}
                """
            ).strip(),
        }
    ]
    for p in images_for_llm:
        user_parts.append(_b64_data_url(p))

    parsed, raw = _chat_json(model=model, system=None, user_content=user_parts, max_tokens=max_tokens)
    return parsed or {"raw_text": raw}


def analyze_video_ad(
    *,
    model: str,
    ad_meta: dict[str, Any],
    frame_paths: list[pathlib.Path],
    transcript: str,
    ad_text: str,
    palette_overall: list[str],
    max_tokens: int,
) -> dict[str, Any]:
    # Limit payload: first 30 frames (1 fps for 30s cap) is already sizeable.
    frames_for_llm = frame_paths[:30]

    user_parts: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": textwrap.dedent(
                f"""
                You are analyzing a Meta Ads Library VIDEO ad for a creative inspiration library.

                You will be given 1 frame per second (up to 30 seconds) in chronological order.

                Return a single JSON object with these keys:
                - ad_summary: string (1-2 sentences)
                - hook: string (what the ad uses as the hook; reference transcript/opening frames)
                - hook_timestamp_s: integer (best-effort)
                - timeline: list of objects, each with keys: t_s (int), visual (string), on_screen_text (string|null), motion_editing (string|null)
                - style: object with keys: color_palette (list[string hex]), typography, layout, imagery_style, motion_style, sound_style
                - primary_message: string
                - cta_offer: object with keys: cta, offer, urgency, audience
                - inspiration_notes: list[string] (actionable tactics)

                Context:
                - ad_meta: {json.dumps(ad_meta, ensure_ascii=True)}
                - extracted_text: {json.dumps(ad_text[:2000], ensure_ascii=True)}
                - transcript (first 30s): {json.dumps(transcript[:4000], ensure_ascii=True)}
                - computed_overall_palette: {json.dumps(palette_overall, ensure_ascii=True)}

                Frames are ordered from t=0 to t={len(frames_for_llm)-1}.
                """
            ).strip(),
        }
    ]
    for p in frames_for_llm:
        user_parts.append(_b64_data_url(p))

    parsed, raw = _chat_json(model=model, system=None, user_content=user_parts, max_tokens=max_tokens)
    return parsed or {"raw_text": raw}


def _find_existing_media_files(*, out_dir: pathlib.Path, ad_dir: pathlib.Path, meta_obj: dict[str, Any]) -> tuple[list[pathlib.Path], list[pathlib.Path]]:
    imgs: list[pathlib.Path] = []
    vids: list[pathlib.Path] = []

    rel_imgs = meta_obj.get("downloaded_images")
    if isinstance(rel_imgs, list):
        for r in rel_imgs:
            p = out_dir / str(r)
            if p.exists():
                imgs.append(p)

    rel_vids = meta_obj.get("downloaded_videos")
    if isinstance(rel_vids, list):
        for r in rel_vids:
            p = out_dir / str(r)
            if p.exists():
                vids.append(p)

    # Fall back to scanning bundle dirs if meta.json doesn't have paths (or they moved).
    if not imgs:
        imgs = sorted((ad_dir / "images").glob("image_*.*"))
    if not vids:
        vids = sorted((ad_dir / "video").glob("video_*.*"))

    return imgs, vids


def _reanalyze_from_existing_bundle(
    *,
    model: str,
    out_dir: pathlib.Path,
    ad_dir: pathlib.Path,
    meta_obj: dict[str, Any],
    fps: int,
    max_video_seconds: int,
    transcribe_model: str,
) -> tuple[dict[str, Any], str]:
    """
    Re-runs analysis using whatever creative files already exist on disk.
    Extracts frames/audio/transcript if missing. Does not scrape network.
    """
    kind = str(meta_obj.get("kind") or "").strip() or "unknown"
    ad_text = str(meta_obj.get("extracted_text") or "")

    imgs, vids = _find_existing_media_files(out_dir=out_dir, ad_dir=ad_dir, meta_obj=meta_obj)
    analysis_inputs_dir = ad_dir / "analysis_inputs"

    transcript = ""
    if kind == "video" or (kind == "unknown" and vids):
        if not vids:
            return {"error": "missing_video_assets"}, ""
        video_path = vids[0]
        frames_dir = ad_dir / "frames"
        audio_path = ad_dir / "audio" / "audio.mp3"
        transcript_path = ad_dir / "audio" / "transcript.txt"

        if not frames_dir.exists() or not any(frames_dir.glob("frame_*.jpg")):
            _extract_frames(
                video_path,
                frames_dir,
                fps=max(1, fps),
                max_seconds=max(1, max_video_seconds),
            )
        if not audio_path.exists():
            _extract_audio(video_path, audio_path, max_seconds=max(1, max_video_seconds))
        if transcript_path.exists():
            transcript = transcript_path.read_text(encoding="utf-8").strip()
        if not transcript and audio_path.exists():
            transcript = _transcribe_audio(audio_path=audio_path, model=transcribe_model)
            _write_text(transcript_path, transcript + "\n")

        max_frames = max(1, min(30, max_video_seconds * max(1, fps)))
        frame_paths = sorted(frames_dir.glob("frame_*.jpg"))[:max_frames]
        llm_frames: list[pathlib.Path] = []
        for fp in frame_paths:
            llm_frames.append(
                _downscale_for_llm(
                    fp,
                    analysis_inputs_dir / "frames" / fp.name,
                    max_side_px=768,
                    jpeg_quality=70,
                )
            )

        palette_overall: list[str] = []
        try:
            if llm_frames:
                palette_overall = _dominant_colors_hex(llm_frames[0], n=6)
        except Exception:
            palette_overall = []

        analysis_obj = analyze_video_ad(
            model=model,
            ad_meta=meta_obj,
            frame_paths=llm_frames,
            transcript=transcript,
            ad_text=ad_text,
            palette_overall=palette_overall,
            max_tokens=2000,
        )
        return analysis_obj, transcript

    # Image ad.
    if not imgs:
        return {"error": "missing_image_assets"}, ""

    llm_images: list[pathlib.Path] = []
    palette_by_image: dict[str, list[str]] = {}
    for img in imgs[:5]:
        llm_img = _downscale_for_llm(
            img,
            analysis_inputs_dir / "images" / (img.stem + ".jpg"),
            max_side_px=1024,
            jpeg_quality=75,
        )
        llm_images.append(llm_img)
        try:
            palette_by_image[llm_img.name] = _dominant_colors_hex(llm_img, n=6)
        except Exception:
            palette_by_image[llm_img.name] = []

    analysis_obj = analyze_image_ad(
        model=model,
        ad_meta=meta_obj,
        image_paths=llm_images,
        ad_text=ad_text,
        palette_by_image=palette_by_image,
        max_tokens=1200,
    )
    return analysis_obj, ""


def _format_ad_text(details: AdDetails) -> str:
    parts: list[str] = []
    for label, xs in (
        ("message", details.messages),
        ("headline", details.headlines),
        ("description", details.descriptions),
    ):
        for x in xs:
            x = (x or "").strip()
            if not x:
                continue
            parts.append(f"[{label}] {x}")
    return "\n".join(parts).strip()


def _write_daily_report(
    *,
    report_path: pathlib.Path,
    out_dir: pathlib.Path,
    run_date: str,
    results: list[dict[str, Any]],
) -> None:
    lines: list[str] = []
    lines.append(f"# Meta Ads Library Tracker ({run_date})")
    lines.append("")
    for rec in results:
        adv = rec.get("advertiser") or {}
        adv_key = adv.get("key") or "advertiser"
        adv_url = adv.get("url") or ""
        lines.append(f"## {adv_key}")
        if adv_url:
            lines.append(f"- URL: {adv_url}")
        ads = rec.get("top_ads") or []
        lines.append(f"- Top ads: {len(ads)}")
        lines.append("")
        for ad in ads:
            ad_id = ad.get("ad_archive_id") or ""
            days = ad.get("days_running")
            started = ad.get("started_running") or ""
            kind = ad.get("kind") or ""
            hook = ((ad.get("analysis") or {}).get("hook") or "").strip()
            summary = ((ad.get("analysis") or {}).get("ad_summary") or "").strip()
            bundle_dir = ad.get("bundle_dir") or ""
            lines.append(f"### {ad_id} ({kind})")
            lines.append(f"- Started: {started} ({days} days running)")
            if hook:
                lines.append(f"- Hook: {hook}")
            if summary:
                lines.append(f"- Summary: {summary}")
            if bundle_dir:
                lines.append(f"- Bundle: `{bundle_dir}`")
            lines.append("")
    _write_text(report_path, "\n".join(lines).rstrip() + "\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape Meta Ads Library advertiser URLs, find longest-running active ads, and generate creative bundles + analysis.",
    )
    parser.add_argument(
        "--dotenv",
        type=str,
        default="auto",
        help="Load env vars from a .env file. Use 'auto' (default), 'off', or a path to a .env file.",
    )
    parser.add_argument(
        "--dotenv-override",
        action="store_true",
        help="If set, values from .env override existing environment variables.",
    )
    parser.add_argument(
        "--analysis-only",
        action="store_true",
        help="Do not scrape/download. Load ad ids from snapshots/<advertiser_key>/latest.json and (re)run analysis on existing bundles.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip downloading creatives (still scrapes ad ids/details). Useful to run in parts.",
    )
    parser.add_argument(
        "--reanalyze-empty",
        action="store_true",
        help="If analysis.json is missing or empty, redo analysis for that ad (no re-download).",
    )
    parser.add_argument(
        "--reanalyze-errors",
        action="store_true",
        help="If analysis.json contains an error, redo analysis for that ad (no re-download).",
    )
    parser.add_argument("--urls-file", type=str, help="Path to a text file with one advertiser URL per line.")
    parser.add_argument("--url", action="append", default=[], help="Advertiser URL (repeatable).")
    parser.add_argument("--out-dir", type=str, default="data/meta-ads-library", help="Output directory.")
    parser.add_argument("--top-n", type=int, default=5, help="Number of longest-running active ads to keep per advertiser.")
    parser.add_argument("--max-video-seconds", type=int, default=30, help="Max seconds to analyze per video.")
    parser.add_argument("--fps", type=int, default=1, help="Frames per second to extract for videos.")
    parser.add_argument(
        "--vision-model",
        type=str,
        default="gpt-5-mini-2025-08-07",
        help="Vision-capable model for creative analysis.",
    )
    parser.add_argument("--transcribe-model", type=str, default="whisper-1", help="OpenAI transcription model.")
    parser.add_argument("--timeout-s", type=int, default=60, help="Per-page timeout in seconds.")
    parser.add_argument("--max-scrolls", type=int, default=25, help="Max scroll iterations on advertiser page.")
    parser.add_argument("--stall-iters", type=int, default=3, help="Stop scrolling after this many no-progress iterations.")
    parser.add_argument("--scroll-px", type=int, default=2400, help="Pixels to scroll each iteration.")
    parser.add_argument("--headful", action="store_true", help="Run browser headful (for debugging).")
    parser.add_argument(
        "--browser-channel",
        type=str,
        default="chrome",
        help="Playwright Chromium channel to use (default: chrome). Use empty string to use bundled Playwright Chromium.",
    )
    parser.add_argument(
        "--allow-channel-fallback",
        action="store_true",
        help="If set, fall back to bundled Playwright Chromium when launching the requested --browser-channel fails.",
    )
    parser.add_argument("--debug", action="store_true", help="Save extra debug artifacts (lightweight).")
    parser.add_argument("--skip-analysis", action="store_true", help="Download creatives but skip OpenAI analysis.")
    parser.add_argument("--force", action="store_true", help="Re-download/re-analyze even if bundle exists.")
    args = parser.parse_args(argv)

    _maybe_load_dotenv(args.dotenv, override=bool(args.dotenv_override))

    urls: list[str] = []
    if args.urls_file:
        urls.extend(_read_text_lines(pathlib.Path(args.urls_file)))
    urls.extend([u for u in (args.url or []) if (u or "").strip()])
    urls = [u.strip() for u in urls if u.strip()]
    if not urls:
        _print_stderr("No advertiser URLs provided. Use --urls-file or --url.")
        return 2

    for u in urls:
        if "facebook.com/ads/library" not in u:
            _print_stderr(f"[WARN] URL does not look like an Ads Library URL: {u}")

    _ensure_ffmpeg()
    if not args.analysis_only:
        _require_playwright()

    out_dir = pathlib.Path(args.out_dir)
    run_date = _today_local().isoformat()
    reports_dir = out_dir / "reports"
    snapshots_dir = out_dir / "snapshots"
    creatives_dir = out_dir / "creatives"

    results: list[dict[str, Any]] = []

    from playwright.sync_api import sync_playwright

    if args.analysis_only:
        for advertiser_url in urls:
            page_id = _parse_view_all_page_id(advertiser_url) or ""
            advertiser_key = _slugify(page_id) if page_id else _slugify(advertiser_url)
            advertiser_rec: dict[str, Any] = {"key": advertiser_key, "url": advertiser_url, "page_id": page_id}

            snap_ads = _load_snapshot_ads(snapshots_dir=snapshots_dir, advertiser_key=advertiser_key) or []
            out_ads: list[dict[str, Any]] = []

            for a in snap_ads[: args.top_n]:
                ad_id = str(a.get("ad_archive_id") or "").strip()
                if not ad_id:
                    continue
                ad_dir = creatives_dir / advertiser_key / ad_id
                analysis_path = ad_dir / "analysis.json"
                meta_path = ad_dir / "meta.json"

                meta_obj = _load_json(meta_path) if meta_path.exists() else None
                analysis_obj = _load_json(analysis_path) if analysis_path.exists() else None

                if meta_obj is None:
                    _print_stderr(f"[WARN] Missing meta.json for ad {ad_id} ({advertiser_key}); skipping.")
                    continue

                needs_rerun = False
                if not args.skip_analysis:
                    if analysis_obj is None:
                        needs_rerun = True
                    if args.reanalyze_errors and isinstance(analysis_obj, dict) and (analysis_obj.get("error") or "").strip():
                        needs_rerun = True
                    if args.reanalyze_empty and _analysis_needs_rerun(analysis_obj if isinstance(analysis_obj, dict) else None):
                        needs_rerun = True

                transcript = str(a.get("transcript") or "").strip()
                if not args.skip_analysis and (needs_rerun or args.force):
                    try:
                        analysis_obj, transcript = _reanalyze_from_existing_bundle(
                            model=args.vision_model,
                            out_dir=out_dir,
                            ad_dir=ad_dir,
                            meta_obj=meta_obj,
                            fps=max(1, args.fps),
                            max_video_seconds=max(1, args.max_video_seconds),
                            transcribe_model=args.transcribe_model,
                        )
                    except Exception as e:
                        _print_stderr(f"[ERROR] OpenAI/analysis failed for ad {ad_id}: {e}")
                        analysis_obj = {"error": str(e)}
                    _json_dump(analysis_path, analysis_obj)

                out_ads.append(
                    {
                        "ad_archive_id": ad_id,
                        "started_running": a.get("started_running") or meta_obj.get("started_running") or "",
                        "days_running": a.get("days_running") or meta_obj.get("days_running") or None,
                        "kind": a.get("kind") or meta_obj.get("kind") or "unknown",
                        "bundle_dir": _as_relpath(ad_dir, out_dir),
                        "analysis": analysis_obj,
                        "transcript": transcript if transcript else None,
                    }
                )

            snapshot_obj = {"run_date": run_date, "advertiser": advertiser_rec, "top_ads": out_ads}
            snap_path = snapshots_dir / advertiser_key / f"{run_date}.json"
            _json_dump(snap_path, snapshot_obj)
            _json_dump(snapshots_dir / advertiser_key / "latest.json", snapshot_obj)
            results.append(snapshot_obj)

        report_path = reports_dir / f"{run_date}.md"
        _write_daily_report(report_path=report_path, out_dir=out_dir, run_date=run_date, results=results)
        return 0

    with sync_playwright() as p:
        launch_kwargs: dict[str, Any] = {"headless": not args.headful}
        channel = (args.browser_channel or "").strip()
        if channel:
            launch_kwargs["channel"] = channel
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception:
            if channel and args.allow_channel_fallback:
                # Fallback for environments without the specified channel installed.
                launch_kwargs.pop("channel", None)
                browser = p.chromium.launch(**launch_kwargs)
            raise
        context = browser.new_context(user_agent=DEFAULT_USER_AGENT, viewport={"width": 1280, "height": 900})
        try:
            for advertiser_url in urls:
                page_id = _parse_view_all_page_id(advertiser_url) or ""
                advertiser_key = _slugify(page_id) if page_id else _slugify(advertiser_url)
                adv_debug_dir = (out_dir / "debug" / advertiser_key) if args.debug else None

                page = context.new_page()
                try:
                    try:
                        top_ads = scrape_advertiser_active_ads(
                            page=page,
                            advertiser_url=advertiser_url,
                            top_n=args.top_n,
                            max_scrolls=args.max_scrolls,
                            stall_iters=args.stall_iters,
                            scroll_px=args.scroll_px,
                            timeout_s=args.timeout_s,
                            debug_dir=adv_debug_dir,
                        )
                    except Exception as e:
                        _print_stderr(f"[ERROR] Failed to scrape advertiser page ({advertiser_key}): {e}")
                        top_ads = []
                finally:
                    page.close()

                advertiser_rec: dict[str, Any] = {"key": advertiser_key, "url": advertiser_url, "page_id": page_id}
                out_ads: list[dict[str, Any]] = []

                for cand in top_ads:
                    ad_id = cand.ad_archive_id
                    ad_dir = creatives_dir / advertiser_key / ad_id
                    analysis_path = ad_dir / "analysis.json"
                    meta_path = ad_dir / "meta.json"

                    if (
                        ad_dir.exists()
                        and meta_path.exists()
                        and (args.skip_analysis or analysis_path.exists())
                        and not args.force
                    ):
                        # If bundle exists, load best-effort.
                        analysis_obj = _load_json(analysis_path) if analysis_path.exists() else None
                        meta_obj = _load_json(meta_path) if meta_path.exists() else None

                        transcript = None
                        try:
                            tpath = ad_dir / "audio" / "transcript.txt"
                            if tpath.exists():
                                transcript = tpath.read_text(encoding="utf-8").strip() or None
                        except Exception:
                            transcript = None

                        needs_rerun = False
                        if not args.skip_analysis:
                            if analysis_obj is None:
                                needs_rerun = True
                            if args.reanalyze_errors and isinstance(analysis_obj, dict) and (analysis_obj.get("error") or "").strip():
                                needs_rerun = True
                            if args.reanalyze_empty and _analysis_needs_rerun(analysis_obj if isinstance(analysis_obj, dict) else None):
                                needs_rerun = True

                        if meta_obj is not None and not args.skip_analysis and needs_rerun:
                            try:
                                analysis_obj, t = _reanalyze_from_existing_bundle(
                                    model=args.vision_model,
                                    out_dir=out_dir,
                                    ad_dir=ad_dir,
                                    meta_obj=meta_obj,
                                    fps=max(1, args.fps),
                                    max_video_seconds=max(1, args.max_video_seconds),
                                    transcribe_model=args.transcribe_model,
                                )
                                transcript = t.strip() or transcript
                            except Exception as e:
                                _print_stderr(f"[ERROR] OpenAI/analysis failed for ad {ad_id}: {e}")
                                analysis_obj = {"error": str(e)}
                            _json_dump(analysis_path, analysis_obj)
                        out_ads.append(
                            {
                                "ad_archive_id": ad_id,
                                "started_running": cand.started_running.isoformat(),
                                "days_running": cand.days_running,
                                "kind": (meta_obj or {}).get("kind") or "unknown",
                                "bundle_dir": _as_relpath(ad_dir, out_dir),
                                "analysis": analysis_obj,
                                "transcript": transcript,
                            }
                        )
                        continue

                    try:
                        details = scrape_ad_details(context=context, ad_archive_id=ad_id, timeout_s=args.timeout_s)
                        ad_text = _format_ad_text(details)

                        # Download creatives.
                        images_dir = ad_dir / "images"
                        videos_dir = ad_dir / "video"
                        frames_dir = ad_dir / "frames"
                        analysis_inputs_dir = ad_dir / "analysis_inputs"

                        downloaded_images: list[pathlib.Path] = []
                        for idx, url in enumerate(details.image_urls[:10]):
                            ext = _guess_ext_from_url(url, default=".jpg")
                            out_path = images_dir / f"image_{idx:02d}{ext}"
                            ok = _download_via_playwright_request(
                                request_ctx=context.request, url=url, out_path=out_path, timeout_s=args.timeout_s
                            )
                            if ok:
                                downloaded_images.append(out_path)

                        downloaded_videos: list[pathlib.Path] = []
                        for idx, url in enumerate(details.video_urls[:3]):
                            url = (url or "").strip()
                            if not url:
                                continue

                            # HLS playlists should be downloaded via ffmpeg into an MP4 (best-effort).
                            if ".m3u8" in url:
                                out_path = videos_dir / f"video_{idx:02d}.mp4"
                                ok = _download_hls_with_ffmpeg(
                                    url,
                                    out_path=out_path,
                                    max_seconds=max(1, args.max_video_seconds),
                                    user_agent=DEFAULT_USER_AGENT,
                                )
                            else:
                                ext = _guess_ext_from_url(url, default=".mp4")
                                out_path = videos_dir / f"video_{idx:02d}{ext}"
                                ok = _download_via_playwright_request(
                                    request_ctx=context.request, url=url, out_path=out_path, timeout_s=args.timeout_s
                                )

                            if ok:
                                downloaded_videos.append(out_path)

                        kind: Literal["video", "image"] = "video" if downloaded_videos else "image"

                        meta_obj: dict[str, Any] = {
                            "ad_archive_id": ad_id,
                            "advertiser": advertiser_rec,
                            "started_running": cand.started_running.isoformat(),
                            "days_running": cand.days_running,
                            "detail_url": details.detail_url,
                            "page_title": details.page_title,
                            "kind": kind,
                            "extracted_text": ad_text,
                            "downloaded_images": [_as_relpath(p, out_dir) for p in downloaded_images],
                            "downloaded_videos": [_as_relpath(p, out_dir) for p in downloaded_videos],
                            "run_date": run_date,
                        }
                        _json_dump(meta_path, meta_obj)

                        analysis_obj: dict[str, Any] | None = None
                        transcript = ""

                        if not args.skip_analysis:
                            try:
                                if kind == "video":
                                    # Pick first video.
                                    video_path = downloaded_videos[0]
                                    audio_path = ad_dir / "audio" / "audio.mp3"
                                    frame_dir = frames_dir

                                    frame_paths = _extract_frames(
                                        video_path,
                                        frame_dir,
                                        fps=max(1, args.fps),
                                        max_seconds=max(1, args.max_video_seconds),
                                    )
                                    _extract_audio(video_path, audio_path, max_seconds=max(1, args.max_video_seconds))
                                    transcript = _transcribe_audio(audio_path=audio_path, model=args.transcribe_model)
                                    _write_text(ad_dir / "audio" / "transcript.txt", transcript + "\n")

                                    # Build LLM inputs (downscaled copies).
                                    llm_frames: list[pathlib.Path] = []
                                    max_frames = max(1, min(30, max(1, args.max_video_seconds) * max(1, args.fps)))
                                    for fp in frame_paths[:max_frames]:
                                        llm_frames.append(
                                            _downscale_for_llm(
                                                fp,
                                                analysis_inputs_dir / "frames" / fp.name,
                                                max_side_px=768,
                                                jpeg_quality=70,
                                            )
                                        )

                                    palette_overall: list[str] = []
                                    try:
                                        if llm_frames:
                                            palette_overall = _dominant_colors_hex(llm_frames[0], n=6)
                                    except Exception:
                                        palette_overall = []

                                    analysis_obj = analyze_video_ad(
                                        model=args.vision_model,
                                        ad_meta=meta_obj,
                                        frame_paths=llm_frames,
                                        transcript=transcript,
                                        ad_text=ad_text,
                                        palette_overall=palette_overall,
                                        max_tokens=2000,
                                    )
                                else:
                                    # Image ad.
                                    llm_images: list[pathlib.Path] = []
                                    palette_by_image: dict[str, list[str]] = {}
                                    for img in downloaded_images[:5]:
                                        llm_img = _downscale_for_llm(
                                            img,
                                            analysis_inputs_dir / "images" / (img.stem + ".jpg"),
                                            max_side_px=1024,
                                            jpeg_quality=75,
                                        )
                                        llm_images.append(llm_img)
                                        try:
                                            palette_by_image[llm_img.name] = _dominant_colors_hex(llm_img, n=6)
                                        except Exception:
                                            palette_by_image[llm_img.name] = []

                                    analysis_obj = analyze_image_ad(
                                        model=args.vision_model,
                                        ad_meta=meta_obj,
                                        image_paths=llm_images,
                                        ad_text=ad_text,
                                        palette_by_image=palette_by_image,
                                        max_tokens=1500,
                                    )
                            except Exception as e:
                                _print_stderr(f"[ERROR] OpenAI/analysis failed for ad {ad_id}: {e}")
                                analysis_obj = {"error": str(e)}

                            if analysis_obj is not None:
                                _json_dump(analysis_path, analysis_obj)

                        out_ads.append(
                            {
                                "ad_archive_id": ad_id,
                                "started_running": cand.started_running.isoformat(),
                                "days_running": cand.days_running,
                                "kind": kind,
                                "bundle_dir": _as_relpath(ad_dir, out_dir),
                                "analysis": analysis_obj,
                                "transcript": transcript if transcript else None,
                            }
                        )
                    except Exception as e:
                        _print_stderr(f"[ERROR] Failed to process ad {ad_id} ({advertiser_key}): {e}")
                        err_meta = {
                            "ad_archive_id": ad_id,
                            "advertiser": advertiser_rec,
                            "started_running": cand.started_running.isoformat(),
                            "days_running": cand.days_running,
                            "run_date": run_date,
                            "error": str(e),
                        }
                        _json_dump(meta_path, err_meta)
                        out_ads.append(
                            {
                                "ad_archive_id": ad_id,
                                "started_running": cand.started_running.isoformat(),
                                "days_running": cand.days_running,
                                "kind": "unknown",
                                "bundle_dir": _as_relpath(ad_dir, out_dir),
                                "error": str(e),
                            }
                        )

                snapshot_obj = {
                    "run_date": run_date,
                    "advertiser": advertiser_rec,
                    "top_ads": out_ads,
                }
                snap_path = snapshots_dir / advertiser_key / f"{run_date}.json"
                _json_dump(snap_path, snapshot_obj)
                _json_dump(snapshots_dir / advertiser_key / "latest.json", snapshot_obj)

                results.append(snapshot_obj)

                # Be polite.
                time.sleep(1.0)
        finally:
            context.close()
            browser.close()

    report_path = reports_dir / f"{run_date}.md"
    _write_daily_report(report_path=report_path, out_dir=out_dir, run_date=run_date, results=results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
