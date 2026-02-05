#!/usr/bin/env python3
"""
Activate local repo skills by installing them into the Codex skills directory.

Default behavior is to create symlinks:
  ~/.codex/skills/<skill-name> -> <repo>/skills/<skill-folder>

This makes iteration fast (edits in the repo reflect immediately).

Usage:
  python3 scripts/activate_local_skills.py
  python3 scripts/activate_local_skills.py --mode copy
  python3 scripts/activate_local_skills.py --dest ~/.codex/skills --only competitor-updates-analysis
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys
from typing import Iterable


def _repo_root() -> pathlib.Path:
    # <repo>/scripts/activate_local_skills.py
    return pathlib.Path(__file__).resolve().parents[1]


def _default_dest_dir() -> pathlib.Path:
    codex_home = (os.environ.get("CODEX_HOME") or "").strip()
    if codex_home:
        return pathlib.Path(codex_home).expanduser() / "skills"
    return pathlib.Path("~/.codex/skills").expanduser()


def _iter_skill_dirs(skills_dir: pathlib.Path) -> Iterable[pathlib.Path]:
    if not skills_dir.is_dir():
        return []
    for p in sorted(skills_dir.iterdir()):
        if not p.is_dir():
            continue
        if (p / "SKILL.md").is_file():
            yield p


def _parse_skill_name(skill_md: pathlib.Path) -> str | None:
    # Minimal YAML frontmatter parser: reads `name: ...` from the first frontmatter block.
    try:
        lines = skill_md.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        s = line.strip()
        if s == "---":
            break
        if not s or s.startswith("#"):
            continue
        if s.startswith("name:"):
            val = s[len("name:") :].strip().strip("'\"")
            return val or None
    return None


def _is_same_symlink(dst: pathlib.Path, src: pathlib.Path) -> bool:
    if not dst.is_symlink():
        return False
    try:
        target = dst.readlink()
    except OSError:
        return False
    # Normalize relative symlinks against the dst parent.
    if not target.is_absolute():
        target = (dst.parent / target).resolve()
    return target.resolve() == src.resolve()


def _install_symlink(src: pathlib.Path, dst: pathlib.Path) -> tuple[bool, str]:
    if dst.exists() or dst.is_symlink():
        if _is_same_symlink(dst, src):
            return False, "already linked"
        return False, "exists (not touching)"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.symlink_to(src)
    return True, "linked"


def _install_copy(src: pathlib.Path, dst: pathlib.Path) -> tuple[bool, str]:
    if dst.exists() or dst.is_symlink():
        return False, "exists (not touching)"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, symlinks=True)
    return True, "copied"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Install local repo skills into ~/.codex/skills (or $CODEX_HOME/skills).")
    ap.add_argument("--dest", default=str(_default_dest_dir()), help="Destination skills directory.")
    ap.add_argument("--mode", choices=["symlink", "copy"], default="symlink", help="Install mode.")
    ap.add_argument(
        "--only",
        action="append",
        default=[],
        help="Skill name(s) to install (repeatable). Defaults to all local skills.",
    )
    args = ap.parse_args(argv)

    repo = _repo_root()
    skills_dir = repo / "skills"
    dest_dir = pathlib.Path(args.dest).expanduser()
    only = {s.strip() for s in (args.only or []) if (s or "").strip()}

    install_fn = _install_symlink if args.mode == "symlink" else _install_copy

    found = 0
    installed = 0
    skipped = 0

    for skill_dir in _iter_skill_dirs(skills_dir):
        found += 1
        name = _parse_skill_name(skill_dir / "SKILL.md") or skill_dir.name
        if only and name not in only and skill_dir.name not in only:
            continue

        dst = dest_dir / name
        ok, msg = install_fn(skill_dir, dst)
        if ok:
            installed += 1
        else:
            skipped += 1
        print(f"{name}\t{msg}\t{dst}")

    if found == 0:
        print(f"No skills found under: {skills_dir}", file=sys.stderr)
        return 2

    print(f"\nSummary: installed={installed} skipped={skipped} dest={dest_dir}")
    if installed > 0:
        print("Restart Codex to pick up newly installed skills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

