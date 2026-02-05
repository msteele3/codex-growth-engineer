#!/usr/bin/env python3
"""
Fetch new IMAP emails since the previous run, filter for "codex" in the subject,
and emit a timestamped markdown summary.

State is stored outside the repo (under $CODEX_HOME) so it persists across
Codex automation runs (which often run in fresh git worktrees).
"""

from __future__ import annotations

import argparse
import datetime as dt
import email
import email.header
import email.parser
import email.policy
import hashlib
import html
import json
import os
import re
import sys
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import imaplib


DEFAULT_MAILBOX = "INBOX"


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def _decode_header_value(value: str) -> str:
    parts = email.header.decode_header(value)
    out: list[str] = []
    for text, charset in parts:
        if isinstance(text, bytes):
            enc = charset or "utf-8"
            try:
                out.append(text.decode(enc, errors="replace"))
            except LookupError:
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _read_dotenv(path: Path) -> dict[str, str]:
    """
    Tiny .env loader (KEY=VALUE, optional quotes). Does not support export/inline comments.
    """
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        env[k] = v
    return env


def _git_worktree_paths() -> list[Path]:
    """
    Best-effort: if running inside a git worktree, discover other worktrees and try to find
    a .env in one of them (e.g., your main checkout).
    """
    import subprocess

    try:
        cp = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []

    if cp.returncode != 0:
        return []

    paths: list[Path] = []
    for line in cp.stdout.splitlines():
        if line.startswith("worktree "):
            p = line[len("worktree ") :].strip()
            if p:
                paths.append(Path(p))
    return paths


def _find_dotenv() -> Optional[Path]:
    # 1) Local .env in current directory or parents.
    cur = Path.cwd().resolve()
    for p in [cur] + list(cur.parents):
        candidate = p / ".env"
        if candidate.exists():
            return candidate

    # 2) .env in any git worktree (helps when automations run in a background worktree).
    for wt in _git_worktree_paths():
        candidate = (wt / ".env").resolve()
        if candidate.exists():
            return candidate

    # 3) Optional secrets file in CODEX_HOME.
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    candidate = codex_home / "secrets" / "codex-growth-engineer.env"
    if candidate.exists():
        return candidate

    return None


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    user: str
    password: str
    mailbox: str
    ssl: bool
    subject_contains: str
    all_mailboxes: bool


def _load_config() -> ImapConfig:
    dotenv_path = _find_dotenv()
    dotenv = _read_dotenv(dotenv_path) if dotenv_path else {}

    def get(key: str, default: Optional[str] = None) -> Optional[str]:
        return os.environ.get(key) or dotenv.get(key) or default

    host = get("IMAP_HOST")
    user = get("IMAP_USER")
    password = get("IMAP_PASSWORD")
    mailbox = get("IMAP_MAILBOX", DEFAULT_MAILBOX) or DEFAULT_MAILBOX
    port_s = get("IMAP_PORT", "993")
    ssl_s = get("IMAP_SSL", "true")
    subject_contains = get("IMAP_SUBJECT_CONTAINS", "codex") or "codex"
    all_mailboxes_s = get("IMAP_ALL_MAILBOXES", "false")

    missing = [k for k, v in [("IMAP_HOST", host), ("IMAP_USER", user), ("IMAP_PASSWORD", password)] if not v]
    if missing:
        where = str(dotenv_path) if dotenv_path else "(no .env found)"
        raise SystemExit(
            "Missing IMAP config: "
            + ", ".join(missing)
            + f". Set env vars or add them to .env. Looked in: {where}"
        )

    try:
        port = int(port_s or "993")
    except ValueError:
        raise SystemExit(f"Invalid IMAP_PORT={port_s!r} (expected integer)")

    ssl = str(ssl_s).strip().lower() not in ("0", "false", "no", "off")
    all_mailboxes = str(all_mailboxes_s).strip().lower() in ("1", "true", "yes", "on")

    return ImapConfig(
        host=host or "",
        port=port,
        user=user or "",
        password=password or "",
        mailbox=mailbox,
        ssl=ssl,
        subject_contains=subject_contains,
        all_mailboxes=all_mailboxes,
    )


def _state_dir() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    return codex_home / "state" / "codex-growth-engineer" / "imap"


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _now_local() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _timestamp_for_filename(ts: dt.datetime) -> str:
    # Example: 2026-02-05_124812_123456-0500 (microseconds to avoid collisions)
    return ts.strftime("%Y-%m-%d_%H%M%S_%f%z")


_IMAP_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _imap_search_date(d: dt.date) -> str:
    # IMAP SEARCH date format: 05-Feb-2026 (always English month abbreviations)
    return f"{d.day:02d}-{_IMAP_MONTHS[d.month - 1]}-{d.year:04d}"


def _imap_connect(cfg: ImapConfig) -> imaplib.IMAP4:
    if cfg.ssl:
        return imaplib.IMAP4_SSL(cfg.host, cfg.port)
    return imaplib.IMAP4(cfg.host, cfg.port)


def _imap_quote_mailbox(mailbox: str) -> str:
    """
    IMAP mailbox names with spaces/special chars must be quoted.
    Gmail frequently uses names like: [Gmail]/Sent Mail
    """
    m = mailbox or ""
    if re.fullmatch(r"[A-Za-z0-9_.-]+", m):
        return m
    m = m.replace("\\", "\\\\").replace('"', r"\"")
    return f"\"{m}\""


def _parse_status_uids(status_resp: bytes) -> tuple[Optional[int], Optional[int]]:
    """
    Parse: b'INBOX (UIDVALIDITY 1700000000 UIDNEXT 1234)'
    """
    s = status_resp.decode("utf-8", errors="replace")
    uidv_m = re.search(r"UIDVALIDITY\s+(\d+)", s)
    uidn_m = re.search(r"UIDNEXT\s+(\d+)", s)
    uidvalidity = int(uidv_m.group(1)) if uidv_m else None
    uidnext = int(uidn_m.group(1)) if uidn_m else None
    return uidvalidity, uidnext


def _imap_mailbox_status(imap: imaplib.IMAP4, mailbox: str) -> tuple[Optional[int], Optional[int]]:
    typ, data = imap.status(_imap_quote_mailbox(mailbox), "(UIDVALIDITY UIDNEXT)")
    if typ != "OK" or not data:
        return None, None
    # data is usually like: [b'INBOX (UIDVALIDITY ... UIDNEXT ...)']
    return _parse_status_uids(data[0])


@dataclass
class EmailMeta:
    uid: int
    mailbox: str
    subject: str
    from_: str
    date: str
    message_id: str


def _fetch_header_meta(imap: imaplib.IMAP4, uid: int, mailbox: str) -> EmailMeta:
    typ, data = imap.uid(
        "fetch",
        str(uid),
        "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])",
    )
    if typ != "OK" or not data:
        return EmailMeta(uid=uid, mailbox=mailbox, subject="", from_="", date="", message_id="")

    raw = b""
    for item in data:
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], (bytes, bytearray)):
            raw += bytes(item[1])

    msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(raw)

    subject_raw = msg.get("Subject", "") or ""
    from_raw = msg.get("From", "") or ""
    date_raw = msg.get("Date", "") or ""
    mid_raw = msg.get("Message-ID", "") or ""

    return EmailMeta(
        uid=uid,
        mailbox=mailbox,
        subject=_decode_header_value(subject_raw),
        from_=_decode_header_value(from_raw),
        date=_decode_header_value(date_raw),
        message_id=_decode_header_value(mid_raw),
    )


def _fetch_text_excerpt(imap: imaplib.IMAP4, uid: int, max_chars: int = 400) -> str:
    # Prefer TEXT to avoid downloading attachments; for multipart messages this may include both parts.
    typ, data = imap.uid("fetch", str(uid), "(BODY.PEEK[TEXT])")
    if typ != "OK" or not data:
        return ""
    raw = b""
    for item in data:
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], (bytes, bytearray)):
            raw += bytes(item[1])
    if not raw:
        return ""
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"\r\n", "\n", text).strip()
    text = re.sub(r"[ \t]+", " ", text)
    if len(text) > max_chars:
        return text[: max_chars - 3] + "..."
    return text


def _subject_contains(subject: str, needle: str) -> bool:
    return (needle or "").lower() in (subject or "").lower()


def _fetch_rfc822(imap: imaplib.IMAP4, uid: int) -> bytes:
    typ, data = imap.uid("fetch", str(uid), "(BODY.PEEK[])")
    if typ != "OK" or not data:
        return b""
    raw = b""
    for item in data:
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], (bytes, bytearray)):
            raw += bytes(item[1])
    return raw


def _strip_html_to_text(html_s: str) -> str:
    # Very small "good enough" converter for support emails.
    s = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_s)
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p\s*>", "\n", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = html.unescape(s)
    # Keep actual whitespace chars; avoid patterns that would treat letters like 't' as whitespace.
    s = re.sub(r"[ \t\r]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def _extract_clean_text(msg: email.message.EmailMessage) -> tuple[str, Optional[str]]:
    """
    Returns (text, html) where text is cleaned text for downstream analysis.
    """
    text_plain: Optional[str] = None
    text_html: Optional[str] = None

    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get_content_disposition() or "").lower()
            if disp == "attachment":
                continue
            if ctype == "text/plain" and text_plain is None:
                try:
                    text_plain = part.get_content()
                except Exception:
                    pass
            if ctype == "text/html" and text_html is None:
                try:
                    text_html = part.get_content()
                except Exception:
                    pass
    else:
        ctype = (msg.get_content_type() or "").lower()
        try:
            if ctype == "text/plain":
                text_plain = msg.get_content()
            elif ctype == "text/html":
                text_html = msg.get_content()
        except Exception:
            pass

    if text_plain is not None:
        s = str(text_plain)
        s = re.sub(r"\r\n", "\n", s).strip()
        s = re.sub(r"[ \t]+", " ", s)
        return s, (str(text_html) if text_html is not None else None)

    if text_html is not None:
        return _strip_html_to_text(str(text_html)), str(text_html)

    return "", None


def _safe_id(meta: EmailMeta) -> str:
    # Stable id for filenames.
    base = (meta.message_id or "").strip()
    if not base:
        base = f"{meta.mailbox}:{meta.uid}"
    h = hashlib.sha256(base.encode("utf-8", errors="ignore")).hexdigest()
    return h[:24]


def _emails_dir(state_dir: Path, day: dt.date) -> Path:
    return state_dir / "emails"


def _emails_json_path(state_dir: Path, day: dt.date) -> Path:
    return _emails_dir(state_dir, day) / f"{day.isoformat()}.json"


def _email_record_from_rfc822(meta: EmailMeta, rfc822: bytes, subject_contains: str, include_raw: bool) -> dict[str, Any]:
    msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(rfc822 or b"")
    subj = _decode_header_value(msg.get("Subject", "") or "") or meta.subject
    from_ = _decode_header_value(msg.get("From", "") or "") or meta.from_
    to_ = _decode_header_value(msg.get("To", "") or "")
    date_ = _decode_header_value(msg.get("Date", "") or "") or meta.date
    mid_ = _decode_header_value(msg.get("Message-ID", "") or "") or meta.message_id

    clean_text, html_body = _extract_clean_text(msg)
    rec: dict[str, Any] = {
        "id": _safe_id(meta),
        "mailbox": meta.mailbox,
        "uid": meta.uid,
        "message_id": mid_,
        "date": date_,
        "from": from_,
        "to": to_,
        "subject": subj,
        "subject_contains": subject_contains,
        "clean_text": clean_text,
        "has_html": bool(html_body),
    }
    if include_raw:
        rec["raw_rfc822_b64"] = base64.b64encode(rfc822 or b"").decode("ascii")
    return rec


def _write_daily_emails_json(state_dir: Path, day: dt.date, generated_at: str, records: list[dict[str, Any]]) -> Path:
    out_dir = _emails_dir(state_dir, day)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = _emails_json_path(state_dir, day)
    payload = {"generated_at": generated_at, "emails": records}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def _write_daily_support_summary(codex_home: Path, day: dt.date, generated_at: str, email_json_paths: list[Path]) -> Path:
    """
    Writes a single "support summary" JSON file under ~/.codex/support-email so demo automations
    can ingest one file for the whole day.

    Schema is intentionally compatible with support-summary.cli.json (threads[] with messages[]).
    """
    out_dir = codex_home / "support-email"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"support-summary-{day.isoformat()}.json"

    def norm_subject(s: str) -> str:
        # Drop bracket tags like [support], collapse whitespace, lowercase.
        s = (s or "").strip()
        s = re.sub(r"^\s*(\[[^\]]+\]\s*)+", "", s)
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s

    threads_by_key: dict[str, list[dict[str, Any]]] = {}
    for p in sorted(email_json_paths):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue

        msg = {
            "uid": obj.get("uid", 0),
            "message_id": obj.get("message_id", "") or "",
            "in_reply_to": "",
            "from_addr": obj.get("from", "") or "",
            "to_addrs": obj.get("to", "") or "",
            "date": obj.get("date", "") or "",
            "subject": obj.get("subject", "") or "",
            "norm_subject": obj.get("subject", "") or "",
            "body": obj.get("clean_text", "") or "",
            "mailbox": obj.get("mailbox", "") or "",
            "source_json": str(p),
        }
        # Simple demo grouping: by normalized subject (after removing tags).
        # This intentionally groups multiple message_ids into a single "thread".
        key = norm_subject(msg["subject"]) or (msg["message_id"] or obj.get("id", "") or str(p))
        threads_by_key.setdefault(key, []).append(msg)

    threads: list[dict[str, Any]] = []
    for key, msgs in threads_by_key.items():
        threads.append(
            {
                "thread_index": len(threads),
                "thread_key": key,
                "latest": msgs[-1],
                "messages": msgs,
            }
        )

    summary = {"generated_at": generated_at, "threads": threads}
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path

def _unquote_imap_string(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1]
        s = s.replace(r"\\", "\\").replace(r"\"", '"')
    return s


def _imap_list_mailboxes(imap: imaplib.IMAP4) -> list[str]:
    typ, data = imap.list()
    if typ != "OK" or not data:
        return []
    out: list[str] = []
    for raw in data:
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace")
        # Skip non-selectable mailboxes.
        if "\\Noselect" in line or "\\NoSelect" in line:
            continue
        # Extract the last quoted string (delimiter + mailbox name are both quoted).
        # Example: '(\\HasNoChildren) "/" "[Gmail]/Sent Mail"'
        quoted = re.findall(r'"((?:\\\\.|[^"])*)"', line)
        if quoted:
            out.append(_unquote_imap_string(f"\"{quoted[-1]}\""))
        else:
            out.append(_unquote_imap_string(line.rsplit(" ", 1)[-1]))
    # Ensure INBOX first for readability.
    out = sorted(set(out), key=lambda m: (m.upper() != "INBOX", m))
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mailbox", default=None, help=f"IMAP mailbox (default: env IMAP_MAILBOX or {DEFAULT_MAILBOX})")
    ap.add_argument(
        "--all-mailboxes",
        action="store_true",
        help="Scan all selectable mailboxes (folders/labels).",
    )
    ap.add_argument(
        "--subject-contains",
        default=None,
        help="Case-insensitive substring match on Subject (default: env IMAP_SUBJECT_CONTAINS or 'codex')",
    )
    ap.add_argument(
        "--today",
        action="store_true",
        help=(
            "Scan all messages whose IMAP internal date is today (local time). "
            "Ignores last_uid state and does not update it."
        ),
    )
    ap.add_argument("--max", type=int, default=200, help="Max new messages to scan (safety)")
    ap.add_argument(
        "--include-raw",
        action="store_true",
        help="Include raw RFC822 as base64 in the daily emails JSON (bigger, but self-contained).",
    )
    ap.add_argument("--no-state-write", action="store_true", help="Do not update last seen UID")
    args = ap.parse_args(argv)

    cfg = _load_config()
    override: dict[str, object] = {}
    if args.mailbox:
        override["mailbox"] = args.mailbox
    if args.subject_contains:
        override["subject_contains"] = args.subject_contains
    if args.all_mailboxes:
        override["all_mailboxes"] = True
    if override:
        cfg = ImapConfig(**{**cfg.__dict__, **override})

    state_dir = _state_dir()
    state_path = state_dir / "imap_state.json"
    digest_dir = state_dir / "digests"
    state = _load_state(state_path)

    imap = _imap_connect(cfg)
    try:
        imap.login(cfg.user, cfg.password)
        mode = "today" if args.today else "incremental"
        mailboxes = _imap_list_mailboxes(imap) if (cfg.all_mailboxes or args.all_mailboxes) else [cfg.mailbox]
        if not mailboxes:
            mailboxes = [cfg.mailbox]

        per_box: dict[str, dict[str, int]] = {}
        matched_items: list[EmailMeta] = []
        max_seen_by_box: dict[str, int] = {}
        uidvalidity_by_box: dict[str, Optional[int]] = {}
        uidnext_by_box: dict[str, Optional[int]] = {}

        # Scan each mailbox independently.
        for mailbox in mailboxes:
            last = state.get("mailboxes", {}).get(mailbox, {})
            last_uid = int(last.get("last_uid", 0) or 0)
            last_uidvalidity = last.get("uidvalidity", None)

            uidvalidity, uidnext = _imap_mailbox_status(imap, mailbox)
            uidvalidity_by_box[mailbox] = uidvalidity
            uidnext_by_box[mailbox] = uidnext
            if uidvalidity is not None and last_uidvalidity is not None and int(uidvalidity) != int(last_uidvalidity):
                last_uid = 0

            typ, _ = imap.select(_imap_quote_mailbox(mailbox), readonly=True)
            if typ != "OK":
                continue

            if args.today:
                today = _now_local().date()
                tomorrow = today + dt.timedelta(days=1)
                search_criteria = f"(SINCE {_imap_search_date(today)} BEFORE {_imap_search_date(tomorrow)})"
            else:
                search_criteria = f"(UID {last_uid + 1}:*)"

            typ, data = imap.uid("search", None, search_criteria)
            if typ != "OK":
                continue

            uids: list[int] = []
            if data and data[0]:
                for tok in data[0].split():
                    try:
                        uids.append(int(tok))
                    except ValueError:
                        continue

            uids = sorted(uids)[: max(0, args.max)]
            per_box[mailbox] = {"scanned": len(uids), "matched": 0}
            max_seen_by_box[mailbox] = max(uids) if uids else last_uid

            metas: list[EmailMeta] = []
            for uid in uids:
                metas.append(_fetch_header_meta(imap, uid, mailbox))

            for meta in metas:
                if _subject_contains(meta.subject, cfg.subject_contains):
                    matched_items.append(meta)
                    per_box[mailbox]["matched"] += 1

        # Deduplicate in case the same email appears in multiple folders (common in Gmail).
        deduped: list[EmailMeta] = []
        seen_keys: set[str] = set()
        for meta in matched_items:
            key = meta.message_id or f"{meta.mailbox}:{meta.uid}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(meta)
        matched_items = deduped

        ts = _now_local()
        ts_str = ts.isoformat(timespec="seconds")
        out_lines: list[str] = []
        out_lines.append(f"# Codex Email Summary ({ts_str})")
        out_lines.append("")
        out_lines.append(f"- Mode: `{mode}`")
        out_lines.append(f"- Mailboxes scanned: `{len(mailboxes)}`")
        out_lines.append(f"- Subject filter: contains `{cfg.subject_contains}`")
        out_lines.append(f"- Matches: `{len(matched_items)}`")
        if per_box:
            scanned_total = sum(v["scanned"] for v in per_box.values())
            out_lines.append(f"- Messages scanned: `{scanned_total}`")
        out_lines.append("")

        day = ts.date()
        daily_records: list[dict[str, Any]] = []

        if per_box:
            out_lines.append("## Mailboxes")
            for m in sorted(per_box.keys(), key=lambda x: (x.upper() != "INBOX", x)):
                out_lines.append(f"- `{m}`: scanned `{per_box[m]['scanned']}`, matched `{per_box[m]['matched']}`")
            out_lines.append("")

        if matched_items:
            # Automation #1 responsibility: persist today's matched emails in a single daily JSON file.
            for meta in matched_items:
                typ, _ = imap.select(_imap_quote_mailbox(meta.mailbox), readonly=True)
                if typ != "OK":
                    continue
                rfc822 = _fetch_rfc822(imap, meta.uid)
                daily_records.append(_email_record_from_rfc822(meta, rfc822, cfg.subject_contains, args.include_raw))

            daily_path = _write_daily_emails_json(state_dir, day, ts_str, daily_records)
            out_lines.append("## Saved Emails")
            out_lines.append(f"- Daily JSON: `{daily_path}`")
            out_lines.append("")

            for rec in daily_records:
                out_lines.append("## Email")
                out_lines.append(f"- ID: `{rec.get('id','')}`")
                out_lines.append(f"- Mailbox: `{rec.get('mailbox','')}`")
                out_lines.append(f"- UID: `{rec.get('uid','')}`")
                if rec.get("date"):
                    out_lines.append(f"- Date: {rec['date']}")
                if rec.get("from"):
                    out_lines.append(f"- From: {rec['from']}")
                out_lines.append(f"- Subject: {rec.get('subject') or '(no subject)'}")
                if rec.get("message_id"):
                    out_lines.append(f"- Message-ID: `{rec['message_id']}`")
                if rec.get("clean_text"):
                    out_lines.append("")
                    out_lines.append("Clean Text:")
                    out_lines.append("")
                    out_lines.append("```")
                    ct = str(rec["clean_text"])
                    out_lines.append(ct[:400] + ("..." if len(ct) > 400 else ""))
                    out_lines.append("```")
                out_lines.append("")
        else:
            out_lines.append("No matching emails.")

        digest_dir.mkdir(parents=True, exist_ok=True)
        # Daily filename (date-based) so "run once a day" gives you a stable artifact.
        digest_path = digest_dir / f"codex-email-summary-{ts.date().isoformat()}.md"
        digest_path.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")

        # Print to stdout so automations can capture the summary without relying on file diffs.
        print("\n".join(out_lines).rstrip())
        print("")
        print(f"[saved] {digest_path}")

        # In --today mode we intentionally avoid mutating last_uid state so repeated
        # runs produce the full day's digest without inter-automation interference.
        if not args.no_state_write and not args.today:
            state.setdefault("mailboxes", {})
            for mailbox, max_uid in max_seen_by_box.items():
                state["mailboxes"][mailbox] = {
                    "last_uid": max_uid,
                    "uidvalidity": uidvalidity_by_box.get(mailbox),
                    "updated_at": ts_str,
                }
            _save_state(state_path, state)

    finally:
        try:
            imap.logout()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
