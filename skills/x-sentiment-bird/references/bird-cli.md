# bird CLI (X)

This skill uses the community `bird` CLI to interact with X (Twitter).

Typical commands:

```bash
# Search recent posts
bird search "Companion AI" -n 50
bird search "Companion AI" -n 50 --json

# Read a post by id or URL
bird read <tweet-id-or-url>

# Fetch replies / a thread for context
bird replies <tweet-id-or-url>
bird thread <tweet-id-or-url>
```

Notes:
- Prefer `--json` for agent pipelines.
- The exact JSON shape may vary by `bird` version; scripts in this repo parse defensively.

