---
name: agent-scratchpad
description: Shared, append-only scratchpad for coordinating work across multiple Codex agents in the same repo. Use when agents need to share current tasks, handoffs, pointers to outputs (file paths/commands), open questions, decisions, and status updates, or when an agent wants to leave a question for another agent to answer asynchronously.
---

# Agent Scratchpad

Assume multiple agents are always running. Use the shared scratchpad to reduce duplicated work, coordinate handoffs, and leave questions for other agents.

## Canonical Scratchpad

- Default file: `scratchpad/AGENT_SCRATCHPAD.md` (repo root)
- Helper CLI: `python3 skills/agent-scratchpad/scripts/scratchpad.py ...`

## Quick Start

1. Ensure the scratchpad exists:

```bash
python3 skills/agent-scratchpad/scripts/scratchpad.py init
```

2. Add a note/pointer/task/question:

```bash
python3 skills/agent-scratchpad/scripts/scratchpad.py add --type POINTER --text "Built uploader. Output: /abs/path/to/file.ts. Run: npm test"
python3 skills/agent-scratchpad/scripts/scratchpad.py question --text "Does the uploader need retries? If yes, which backoff?"
```

3. List open questions or show recent entries:

```bash
python3 skills/agent-scratchpad/scripts/scratchpad.py open-questions
python3 skills/agent-scratchpad/scripts/scratchpad.py tail --n 20
```

## Operating Protocol (Multi-Agent)

- Always read `scratchpad/AGENT_SCRATCHPAD.md` before starting non-trivial work.
- Write an entry at the start of work:
  - `TASK`: what you are taking, what you expect to change, and where.
- Write an entry after producing output:
  - `POINTER`: exact file paths, commands, PR/branch name if any, and what changed.
- If blocked, do not stall:
  - leave a `QUESTION` with a concrete ask; other agents should respond with an `ANSWER` that closes the question id.

## Writing Guidelines

- Prefer append-only entries (minimize edits to old text).
- Include concrete pointers: absolute paths, command lines, and “what to look for”.
- Keep entries short; use links/paths to the real artifacts.

If you need the exact entry format, see `skills/agent-scratchpad/references/format.md`.
