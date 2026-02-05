#!/usr/bin/env python3

from __future__ import annotations

import os
import pathlib
import sys


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    print("example-skill: hello")
    print(f"python: {sys.version.split()[0]}")
    print(f"cwd: {pathlib.Path.cwd()}")
    print(f"repo_root: {repo_root}")

    skills_dir = repo_root / "skills"
    if skills_dir.is_dir():
        skill_folders = sorted(p.name for p in skills_dir.iterdir() if p.is_dir())
        print(f"skills/: {', '.join(skill_folders) if skill_folders else '(none)'}")
    else:
        print("skills/: (missing)")

    print(f"env: CODEX_HOME={os.environ.get('CODEX_HOME', '')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

