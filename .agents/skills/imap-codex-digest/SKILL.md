---
name: imap-codex-digest
description: Read IMAP email, filter by subject substring (e.g. "[support]"), and produce a timestamped markdown summary.
---

# IMAP Codex Digest

## What this does

- Connects to IMAP using credentials from `.env` / environment variables.
- Scans emails since the previous run (tracked via IMAP UID state in `$CODEX_HOME/state/...`).
- Filters to emails whose **subject** contains `IMAP_SUBJECT_CONTAINS` (case-insensitive).
- Saves each matched email to `$CODEX_HOME/state/codex-growth-engineer/imap/emails/YYYY-MM-DD/`:
  - `<id>.json` (clean structured fields + `clean_text`)
  - `<id>.eml` (raw RFC822)
- Produces a markdown summary and prints it for the automation inbox.

## How to run

Use the repo script:

```bash
python3 scripts/imap_codex_digest.py
```

Useful options:

```bash
# Daily digest: scan all of today's email (rerunnable; does not depend on last_uid state)
python3 scripts/imap_codex_digest.py --today

# Gmail: include all folders/labels (INBOX, All Mail, etc.)
python3 scripts/imap_codex_digest.py --all-mailboxes
```

## Configuration

Expected env vars (in `.env` is fine):

- `IMAP_HOST` (required)
- `IMAP_USER` (required)
- `IMAP_PASSWORD` (required)
- `IMAP_PORT` (optional, default `993`)
- `IMAP_SSL` (optional, default `true`)
- `IMAP_MAILBOX` (optional, default `INBOX`)
- `IMAP_SUBJECT_CONTAINS` (optional, default `codex`; set to `[support]` to match that tag)
- `IMAP_ALL_MAILBOXES` (optional, default `false`; if `true`, scans all selectable mailboxes)

## Automation usage

In a Codex automation prompt, include `$imap-codex-digest` and ask it to run the command above and post the summary as the automation output.
