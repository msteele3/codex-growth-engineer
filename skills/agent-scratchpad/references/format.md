# Agent Scratchpad Format

The scratchpad is intentionally append-only to minimize merge conflicts and reduce coordination overhead.

## Entry Types

- `TASK`: claim work / announce intent
- `POINTER`: point to an output artifact (files, commands, branches)
- `NOTE`: lightweight context
- `QUESTION`: ask another agent to decide/confirm
- `ANSWER`: answer a question and close it

## Canonical Entry Header

Entries are Markdown headings in this form:

```
## <ISO-ish timestamp> | <TYPE> | agent=<agent> | id=<id>
```

Only `QUESTION` entries require an `id`. `ANSWER` entries should include `closes=<question-id>`.

## Example

```
## 2026-02-05 12:34:56 -0800 | QUESTION | agent=codex | id=Q-20260205-123456-12345
Do we need exponential backoff on retries? If yes, what caps?

## 2026-02-05 12:50:12 -0800 | ANSWER | agent=codex | closes=Q-20260205-123456-12345
Yes. Use exponential backoff with full jitter, cap at 30s, max 5 attempts.
```
