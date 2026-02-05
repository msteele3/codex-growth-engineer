#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import sys
from typing import Iterable


def _repo_root() -> pathlib.Path:
    # <repo>/skills/agent-scratchpad/scripts/scratchpad.py
    return pathlib.Path(__file__).resolve().parents[3]


def _default_scratchpad_path() -> pathlib.Path:
    return _repo_root() / "scratchpad" / "AGENT_SCRATCHPAD.md"


def _now_local() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _format_ts(ts: dt.datetime) -> str:
    # Keep it human-scannable and stable in markdown diffs.
    return ts.strftime("%Y-%m-%d %H:%M:%S %z")


def _agent_name(explicit: str | None) -> str:
    if explicit:
        return explicit
    return (
        os.environ.get("CODEX_AGENT")
        or os.environ.get("AGENT_NAME")
        or os.environ.get("USER")
        or "unknown"
    )


def _agent_role(explicit: str | None) -> str:
    if explicit:
        return explicit
    return (
        os.environ.get("CODEX_AGENT_ROLE")
        or os.environ.get("AGENT_ROLE")
        # If an agent is running via an automation, the automation prompt/description
        # is often the best proxy for "what they do".
        or os.environ.get("CODEX_AUTOMATION_PROMPT")
        or "unknown"
    )


def _ensure_parent_dir(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _init_file(path: pathlib.Path) -> None:
    if path.exists():
        return
    _ensure_parent_dir(path)
    header = """# Agent Scratchpad

Shared, append-only scratchpad for coordinating multiple agents working in this repo.

Protocol:
- Read before starting non-trivial work.
- Append entries (TASK/POINTER/QUESTION/ANSWER) with concrete file paths and commands.
- Prefer leaving a QUESTION over blocking.

---

"""
    path.write_text(header, encoding="utf-8")


def _new_question_id(ts: dt.datetime) -> str:
    # Include microseconds to avoid collisions when the same process emits
    # multiple questions within a single second.
    return f"Q-{ts.strftime('%Y%m%d-%H%M%S-%f')}-{os.getpid()}"


def _append_entry(
    *,
    path: pathlib.Path,
    entry_type: str,
    agent: str,
    role: str,
    text: str,
    entry_id: str | None = None,
    closes: str | None = None,
) -> str | None:
    _init_file(path)

    ts = _now_local()
    if entry_type == "QUESTION" and not entry_id:
        entry_id = _new_question_id(ts)

    parts: list[str] = [_format_ts(ts), entry_type, f"agent={agent}", f"role={role}"]
    if entry_id:
        parts.append(f"id={entry_id}")
    if closes:
        parts.append(f"closes={closes}")

    entry_header = "## " + " | ".join(parts)
    body = text.strip()
    if not body:
        raise ValueError("text must be non-empty")

    # Always append with a blank line before and after to keep diffs simple.
    to_write = f"{entry_header}\n{body}\n\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(to_write)

    return entry_id


def _iter_lines(path: pathlib.Path) -> Iterable[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _parse_open_questions(path: pathlib.Path) -> list[tuple[str, str]]:
    # Returns [(id, header_line), ...] for questions not closed by an ANSWER.
    question_headers: dict[str, str] = {}
    closed: set[str] = set()

    for line in _iter_lines(path):
        if not line.startswith("## "):
            continue

        if "| QUESTION |" in line and "id=" in line:
            # naive but stable: id appears as token "id=..."
            tokens = [t.strip() for t in line.split("|")]
            qid = None
            for t in tokens:
                if t.startswith("id="):
                    qid = t[len("id=") :].strip()
                    break
            if qid:
                question_headers[qid] = line

        if "| ANSWER |" in line and "closes=" in line:
            tokens = [t.strip() for t in line.split("|")]
            for t in tokens:
                if t.startswith("closes="):
                    closed.add(t[len("closes=") :].strip())
                    break

    open_ids = [qid for qid in question_headers.keys() if qid not in closed]
    # Stable ordering: by appearance in file (dict insertion), so preserve that.
    return [(qid, question_headers[qid]) for qid in open_ids]


def cmd_init(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.file)
    _init_file(path)
    print(str(path))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    entry_type = args.type.strip().upper()
    agent = _agent_name(args.agent)
    role = _agent_role(args.role)
    path = pathlib.Path(args.file)
    entry_id = _append_entry(
        path=path,
        entry_type=entry_type,
        agent=agent,
        role=role,
        text=args.text,
        entry_id=None,
    )
    if entry_id:
        print(entry_id)
    return 0


def cmd_question(args: argparse.Namespace) -> int:
    agent = _agent_name(args.agent)
    role = _agent_role(args.role)
    path = pathlib.Path(args.file)
    qid = _append_entry(
        path=path,
        entry_type="QUESTION",
        agent=agent,
        role=role,
        text=args.text,
        entry_id=None,
    )
    print(qid)
    return 0


def cmd_answer(args: argparse.Namespace) -> int:
    agent = _agent_name(args.agent)
    role = _agent_role(args.role)
    path = pathlib.Path(args.file)
    if not args.closes:
        raise ValueError("--closes is required")
    _append_entry(
        path=path,
        entry_type="ANSWER",
        agent=agent,
        role=role,
        text=args.text,
        entry_id=None,
        closes=args.closes.strip(),
    )
    return 0


def cmd_open_questions(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.file)
    open_qs = _parse_open_questions(path)
    if not open_qs:
        print("(no open questions)")
        return 0
    for qid, header in open_qs:
        print(f"{qid}\t{header}")
    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.file)
    lines = list(_iter_lines(path))
    if not lines:
        print("(scratchpad missing or empty)")
        return 0
    n = max(1, int(args.n))
    for line in lines[-n:]:
        print(line)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Shared scratchpad helper for multi-agent coordination.")
    p.set_defaults(func=None)
    p.add_argument("--file", default=str(_default_scratchpad_path()), help="Scratchpad file path.")
    p.add_argument("--agent", default=None, help="Agent name (defaults to env or USER).")
    p.add_argument(
        "--role",
        default=None,
        help="Agent role/what they do (defaults to env; ideally matches automation description).",
    )

    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("init", help="Create the scratchpad file if missing.")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("add", help="Append a NOTE/POINTER/TASK/etc entry.")
    sp.add_argument("--type", required=True, help="Entry type (NOTE, POINTER, TASK, QUESTION, ANSWER).")
    sp.add_argument("--text", required=True, help="Entry body text.")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("question", help="Append a QUESTION entry (auto-generates an id).")
    sp.add_argument("--text", required=True, help="Question text (make it a concrete ask).")
    sp.set_defaults(func=cmd_question)

    sp = sub.add_parser("answer", help="Append an ANSWER entry that closes a QUESTION id.")
    sp.add_argument("--closes", required=True, help="Question id to close.")
    sp.add_argument("--text", required=True, help="Answer text.")
    sp.set_defaults(func=cmd_answer)

    sp = sub.add_parser("open-questions", help="List QUESTION ids that have not been closed by an ANSWER.")
    sp.set_defaults(func=cmd_open_questions)

    sp = sub.add_parser("tail", help="Print the last N lines of the scratchpad file.")
    sp.add_argument("--n", default="50", help="Number of lines.")
    sp.set_defaults(func=cmd_tail)

    return p


def main(argv: list[str]) -> int:
    p = _build_parser()
    args = p.parse_args(argv)
    if not args.func:
        p.print_help()
        return 2
    try:
        return int(args.func(args))
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
