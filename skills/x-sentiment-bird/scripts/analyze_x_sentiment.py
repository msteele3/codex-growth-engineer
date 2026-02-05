#!/usr/bin/env python3
"""
Analyze sentiment on X (Twitter) using the `bird` CLI for data retrieval.

Usage:
  python3 skills/x-sentiment-bird/scripts/analyze_x_sentiment.py --query "Companion AI" -n 30

Requires:
  - `bird` on PATH and authenticated for X access.

Optional:
  - OPENAI_API_KEY for higher-quality sentiment classification.
  - OPENAI_MODEL to override the default model (default: gpt-4.1).

Outputs (by default):
  - data/x-sentiment/raw/<timestamp>.json
  - data/x-sentiment/analysis/<timestamp>.json
  - data/x-sentiment/reports/<timestamp>.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any, Literal


Sentiment = Literal["positive", "neutral", "negative"]


def _utc_stamp() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _json_dump(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _md_write(path: pathlib.Path, s: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s.strip() + "\n", encoding="utf-8")


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _run_bird_json(*, bird_bin: str, query: str, n: int) -> Any:
    cmd = [bird_bin, "search", query, "--json", "-n", str(n)]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        _die(f"`{bird_bin}` not found on PATH. Install/configure bird first, then retry.")
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").splitlines()[-40:])
        _die(f"`bird search` failed (exit {p.returncode}). Stderr tail:\n{tail}".strip())
    out = (p.stdout or "").strip()
    if not out:
        return []
    try:
        return json.loads(out)
    except Exception:
        # Try to salvage a JSON array/object embedded in noise.
        m = re.search(r"(\{.*\}|\[.*\])", out, re.S)
        if not m:
            _die(f"bird output was not JSON (first 2000 chars):\n{out[:2000]}")
        try:
            return json.loads(m.group(1))
        except Exception:
            _die(f"bird output was not valid JSON (first 2000 chars):\n{out[:2000]}")
    raise AssertionError("unreachable")

def _load_json_file(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        _die(f"Failed to read JSON: {path}\n{e}")
    raise AssertionError("unreachable")


def _as_list(x: Any) -> list[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    # Some CLIs wrap results in {data: [...]}
    if isinstance(x, dict):
        for k in ("data", "results", "tweets", "items"):
            if isinstance(x.get(k), list):
                return list(x[k])
    return []


def _pick_first_str(d: dict[str, Any], keys: list[str]) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _pick_int(d: dict[str, Any], keys: list[str]) -> int:
    for k in keys:
        v = d.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip().isdigit():
            try:
                return int(v.strip())
            except Exception:
                pass
    return 0


def _normalize_tweet(raw: dict[str, Any]) -> dict[str, Any]:
    # Parse defensively; bird versions differ.
    tweet_id = _pick_first_str(raw, ["id_str", "id", "tweet_id", "rest_id"])
    url = _pick_first_str(raw, ["url", "tweet_url", "permalink", "permalink_url"])
    text = _pick_first_str(raw, ["full_text", "text", "content"])
    author = _pick_first_str(raw, ["username", "screen_name", "user", "author"])

    likes = _pick_int(raw, ["favorite_count", "like_count", "likes"])
    retweets = _pick_int(raw, ["retweet_count", "repost_count", "retweets"])
    replies = _pick_int(raw, ["reply_count", "replies"])

    created_at = _pick_first_str(raw, ["created_at", "createdAt", "date"])

    return {
        "id": tweet_id,
        "url": url,
        "author": author,
        "created_at": created_at,
        "text": text,
        "metrics": {"likes": likes, "retweets": retweets, "replies": replies},
        "raw": raw,
    }


def _load_openai_client():
    try:
        from openai import OpenAI
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Missing OpenAI Python package. Install with: python3 -m pip install --upgrade openai"
        ) from e
    return OpenAI()


def _chat_json(*, model: str, system: str, user_text: str, max_tokens: int) -> dict[str, Any]:
    client = _load_openai_client()
    # Prefer Chat Completions JSON mode for a single-object response.
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception:
        text = ""

    if not text:
        r = client.responses.create(
            model=model,
            instructions=system,
            input=[{"role": "user", "content": [{"type": "input_text", "text": user_text}]}],
            max_output_tokens=max_tokens,
            text={"format": {"type": "json_object"}},
        )
        text = (getattr(r, "output_text", "") or "").strip()

    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        raise RuntimeError(f"Model did not return valid JSON. Raw (first 2000 chars):\n{text[:2000]}")


def _chunk(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    out: list[list[dict[str, Any]]] = []
    for i in range(0, len(items), max(1, size)):
        out.append(items[i : i + size])
    return out


_POS_WORDS = {
    "love",
    "loved",
    "awesome",
    "great",
    "amazing",
    "nice",
    "good",
    "cool",
    "wow",
    "fantastic",
    "perfect",
    "best",
    "excited",
    "impressed",
    "recommend",
    "recommended",
    "helpful",
    "useful",
    "thanks",
    "thank you",
}

_NEG_WORDS = {
    "hate",
    "hated",
    "awful",
    "terrible",
    "bad",
    "worse",
    "worst",
    "broken",
    "bug",
    "bugs",
    "crash",
    "crashes",
    "scam",
    "spam",
    "creepy",
    "weird",
    "privacy",
    "unsafe",
    "annoying",
    "disappointed",
    "disappointing",
    "refund",
}


def _heuristic_sentiment(text: str) -> tuple[Sentiment, float]:
    t = (text or "").lower()
    if not t.strip():
        return "neutral", 0.2
    score = 0
    for w in _POS_WORDS:
        if w in t:
            score += 1
    for w in _NEG_WORDS:
        if w in t:
            score -= 1
    if score >= 2:
        return "positive", 0.55
    if score <= -2:
        return "negative", 0.55
    if score == 1:
        return "positive", 0.45
    if score == -1:
        return "negative", 0.45
    return "neutral", 0.35


def _analyze_with_openai(*, model: str, tweets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    system = (
        "You classify sentiment for short social posts.\n"
        "Return ONLY JSON.\n"
        "Sentiment labels: positive | neutral | negative.\n"
        "Be conservative: if unsure, choose neutral.\n"
        "Ignore the author's political stance; score only the author's attitude toward the product/topic in the post.\n"
        "If the post is a question or newsy/announcement without clear attitude, choose neutral.\n"
    )
    results: list[dict[str, Any]] = []

    # Chunk to keep prompts small and reduce failure blast radius.
    for part in _chunk(tweets, 15):
        payload = []
        for t in part:
            payload.append(
                {
                    "id": t.get("id") or "",
                    "text": t.get("text") or "",
                    "likes": int(((t.get("metrics") or {}).get("likes") or 0)),
                    "retweets": int(((t.get("metrics") or {}).get("retweets") or 0)),
                }
            )

        user = (
            "Classify each post.\n\n"
            "Return a JSON object with this shape:\n"
            "{\n"
            '  "items": [\n'
            '    {"id": "...", "sentiment": "positive|neutral|negative", "confidence": 0.0-1.0, "themes": ["...","..."]}\n'
            "  ]\n"
            "}\n\n"
            "Posts:\n"
            + json.dumps(payload, ensure_ascii=True, indent=2)
        )

        out = _chat_json(model=model, system=system, user_text=user, max_tokens=1200)
        items = out.get("items")
        if not isinstance(items, list):
            raise RuntimeError("OpenAI response missing `items` array.")
        for it in items:
            if not isinstance(it, dict):
                continue
            sid = str(it.get("id") or "").strip()
            sent = str(it.get("sentiment") or "").strip().lower()
            conf = it.get("confidence")
            themes = it.get("themes")
            if sent not in ("positive", "neutral", "negative"):
                sent = "neutral"
            if not isinstance(conf, (int, float)):
                conf = 0.5
            conf = max(0.0, min(1.0, float(conf)))
            if not isinstance(themes, list) or not all(isinstance(x, str) for x in themes):
                themes = []
            results.append(
                {
                    "id": sid,
                    "sentiment": sent,
                    "confidence": conf,
                    "themes": [x.strip() for x in themes if isinstance(x, str) and x.strip()][:6],
                }
            )

    # Preserve original order; fill any missing as neutral.
    by_id: dict[str, dict[str, Any]] = {r["id"]: r for r in results if r.get("id")}
    out2: list[dict[str, Any]] = []
    for t in tweets:
        tid = str(t.get("id") or "").strip()
        r = by_id.get(tid) if tid else None
        if r:
            out2.append(r)
        else:
            out2.append({"id": tid, "sentiment": "neutral", "confidence": 0.4, "themes": []})
    return out2


def _aggregate(*, tweets: list[dict[str, Any]], labels: list[dict[str, Any]]) -> dict[str, Any]:
    if len(tweets) != len(labels):
        raise RuntimeError("Internal error: tweets/labels length mismatch.")

    rows: list[dict[str, Any]] = []
    for t, l in zip(tweets, labels, strict=True):
        rows.append(
            {
                "id": t.get("id") or "",
                "url": t.get("url") or "",
                "author": t.get("author") or "",
                "created_at": t.get("created_at") or "",
                "text": t.get("text") or "",
                "metrics": t.get("metrics") or {"likes": 0, "retweets": 0, "replies": 0},
                "sentiment": l.get("sentiment") or "neutral",
                "confidence": float(l.get("confidence") or 0.0),
                "themes": l.get("themes") or [],
            }
        )

    totals = {"positive": 0, "neutral": 0, "negative": 0}
    for r in rows:
        s = str(r.get("sentiment") or "neutral")
        if s not in totals:
            s = "neutral"
        totals[s] += 1
        r["sentiment"] = s

    n = max(1, len(rows))
    pct = {k: round(100.0 * v / float(n), 1) for k, v in totals.items()}
    net = round(pct["positive"] - pct["negative"], 1)

    def _likes(r: dict[str, Any]) -> int:
        m = r.get("metrics") or {}
        try:
            return int(m.get("likes") or 0)
        except Exception:
            return 0

    top_pos = sorted([r for r in rows if r["sentiment"] == "positive"], key=_likes, reverse=True)[:3]
    top_neg = sorted([r for r in rows if r["sentiment"] == "negative"], key=_likes, reverse=True)[:3]

    # Theme rollup (best-effort).
    theme_counts: dict[str, int] = {}
    for r in rows:
        for th in r.get("themes") or []:
            s = (th or "").strip()
            if not s:
                continue
            theme_counts[s] = theme_counts.get(s, 0) + 1
    top_themes = sorted(theme_counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:10]

    return {
        "counts": totals,
        "percent": pct,
        "net_sentiment": net,
        "top_positive": top_pos,
        "top_negative": top_neg,
        "themes": [{"theme": k, "count": v} for k, v in top_themes],
        "rows": rows,
    }


def _format_report(*, query: str, stamp: str, agg: dict[str, Any]) -> str:
    pct = agg["percent"]
    net = agg["net_sentiment"]
    counts = agg["counts"]

    def _short(s: str, max_len: int = 280) -> str:
        s = (s or "").strip().replace("\n", " ")
        s = re.sub(r"\\s{2,}", " ", s)
        if len(s) <= max_len:
            return s
        return s[: max_len - 1].rstrip() + "…"

    def _fmt_row(r: dict[str, Any]) -> str:
        url = r.get("url") or ""
        tid = r.get("id") or ""
        who = r.get("author") or ""
        likes = int(((r.get("metrics") or {}).get("likes") or 0))
        sent = r.get("sentiment") or "neutral"
        txt = _short(str(r.get("text") or ""))
        link = url or (f"https://x.com/i/web/status/{tid}" if tid else "")
        return f"- [{sent}] ({likes} likes) {who} {link}\n  - {txt}"

    lines: list[str] = []
    lines.append(f"# X Sentiment Report")
    lines.append("")
    lines.append(f"- Query: `{query}`")
    lines.append(f"- Timestamp (UTC): `{stamp}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Positive: {pct['positive']}% ({counts['positive']})")
    lines.append(f"- Neutral: {pct['neutral']}% ({counts['neutral']})")
    lines.append(f"- Negative: {pct['negative']}% ({counts['negative']})")
    lines.append(f"- Net sentiment: `{net}` (positive% - negative%)")
    lines.append("")

    lines.append("## Top Themes")
    lines.append("")
    if agg["themes"]:
        for t in agg["themes"][:8]:
            lines.append(f"- {t['theme']} ({t['count']})")
    else:
        lines.append("- (no themes extracted)")
    lines.append("")

    lines.append("## Most Liked Positive")
    lines.append("")
    if agg["top_positive"]:
        for r in agg["top_positive"]:
            lines.append(_fmt_row(r))
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Most Liked Negative")
    lines.append("")
    if agg["top_negative"]:
        for r in agg["top_negative"]:
            lines.append(_fmt_row(r))
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Caveats")
    lines.append("")
    lines.append("- Search results are a convenience sample, not representative of all X users.")
    lines.append("- If OPENAI_API_KEY was not set, sentiment uses a heuristic fallback (lower quality).")
    return "\n".join(lines).strip() + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True, help="Search query (e.g. 'Companion AI').")
    ap.add_argument("-n", type=int, default=30, help="Number of recent posts to fetch (default: 30).")
    ap.add_argument("--bird-bin", default="bird", help="Path to bird CLI (default: bird).")
    ap.add_argument(
        "--input-json",
        default="",
        help="If set, skip bird and analyze this existing bird `--json` output instead.",
    )
    ap.add_argument("--out-dir", default="data/x-sentiment", help="Output directory (default: data/x-sentiment).")
    ap.add_argument("--model", default=os.environ.get("OPENAI_MODEL") or "gpt-4.1", help="OpenAI model (default: gpt-4.1).")
    ap.add_argument("--no-openai", action="store_true", help="Force heuristic sentiment (ignore OPENAI_API_KEY).")
    args = ap.parse_args(argv)

    query = str(args.query).strip()
    if not query:
        _die("--query must be non-empty.")
    n = int(args.n)
    if n <= 0 or n > 200:
        _die("-n must be between 1 and 200.")

    stamp = _utc_stamp()
    out_dir = pathlib.Path(args.out_dir)
    raw_path = out_dir / "raw" / f"{stamp}.json"
    analysis_path = out_dir / "analysis" / f"{stamp}.json"
    report_path = out_dir / "reports" / f"{stamp}.md"

    if (args.input_json or "").strip():
        raw = _load_json_file(pathlib.Path(args.input_json).expanduser())
    else:
        raw = _run_bird_json(bird_bin=args.bird_bin, query=query, n=n)
    _json_dump(raw_path, raw)

    items = [_normalize_tweet(x) for x in _as_list(raw) if isinstance(x, dict)]
    # Drop empty-text items; they can confuse both heuristics and LLM.
    tweets = [t for t in items if (t.get("text") or "").strip()]

    use_openai = (not args.no_openai) and bool((os.environ.get("OPENAI_API_KEY") or "").strip())

    labels: list[dict[str, Any]] = []
    if use_openai:
        try:
            labels = _analyze_with_openai(model=str(args.model), tweets=tweets)
        except Exception as e:
            print(f"OpenAI sentiment failed; falling back to heuristic. Error: {e}", file=sys.stderr)
            labels = []

    if not labels:
        labels = []
        for t in tweets:
            s, conf = _heuristic_sentiment(str(t.get("text") or ""))
            labels.append({"id": str(t.get("id") or ""), "sentiment": s, "confidence": conf, "themes": []})

    agg = _aggregate(tweets=tweets, labels=labels)
    analysis_obj = {
        "query": query,
        "timestamp_utc": stamp,
        "raw_path": str(raw_path),
        "used_openai": bool(use_openai and os.environ.get("OPENAI_API_KEY")),
        "model": str(args.model),
        "summary": {k: agg[k] for k in ("counts", "percent", "net_sentiment", "themes")},
        "rows": agg["rows"],
    }
    _json_dump(analysis_path, analysis_obj)
    _md_write(report_path, _format_report(query=query, stamp=stamp, agg=agg))

    print(str(report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
