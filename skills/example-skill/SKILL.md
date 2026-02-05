---
name: example-skill
description: Example skill template for this repository. Use when creating a new Codex skill folder, adding SKILL.md frontmatter + instructions, adding agents/openai.yaml metadata, or bundling simple scripts/references as examples.
---

# Example Skill

Use this as a minimal, copyable template for new skills in this repo.

## What This Skill Contains

- `agents/openai.yaml`: UI metadata (display name, short description, default prompt)
- `scripts/hello_skill.py`: Tiny runnable script that prints basic repo context
- `references/example-notes.md`: Placeholder for reference material

## Quick Start

1. Run the example script:

```bash
python3 skills/example-skill/scripts/hello_skill.py
```

2. Copy this skill folder to start a new skill:

```bash
cp -R skills/example-skill skills/<new-skill-name>
```

Then edit:
- `skills/<new-skill-name>/SKILL.md` frontmatter (`name`, `description`)
- `skills/<new-skill-name>/agents/openai.yaml` (`display_name`, `short_description`, `default_prompt`)
- Add/remove `scripts/`, `references/`, `assets/` as needed

