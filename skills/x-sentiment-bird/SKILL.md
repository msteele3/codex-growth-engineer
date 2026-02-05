---
name: x-sentiment-bird
description: Sentiment analysis for X (Twitter) using the `bird` CLI. Use when asked to assess public sentiment, reactions, or trends on X for a keyword/brand (e.g. "Companion AI"), including requests like "analyze X sentiment", "Twitter sentiment", "what are people saying on X", "scan recent tweets", "summarize positive vs negative feedback", or "net sentiment score".
---

# X Sentiment (bird)

Fetch recent posts from X via the `bird` CLI, classify sentiment (positive/neutral/negative), and produce a concise report with top examples and themes.

## Quick Start

```bash
python3 skills/x-sentiment-bird/scripts/analyze_x_sentiment.py --query "Companion AI" -n 30
```

Outputs (by default):
- Snapshot JSON: `data/x-sentiment/raw/<timestamp>.json`
- Analysis JSON: `data/x-sentiment/analysis/<timestamp>.json`
- Report Markdown: `data/x-sentiment/reports/<timestamp>.md`

## Workflow (Agent)

1. Run `analyze_x_sentiment.py` with a query (and optionally an `--out-dir`).
2. Open the generated markdown report first; only open the raw snapshot JSON if you need to verify details.
3. When summarizing for the user, include:
   - Overall split: % positive / neutral / negative
   - Net sentiment score (pos% - neg%)
   - Top positive and top negative posts (by likes, when available)
   - 3-6 recurring themes, with example quotes
4. Call out caveats:
   - Search results are not a representative sample of all X users.
   - Quotes may be partial; always link/id the post for verification.

## Notes

- This skill expects `bird` to be available on `PATH`. See `references/bird-cli.md` for the commands this skill uses.
- Sentiment classification uses OpenAI when `OPENAI_API_KEY` is set; otherwise it falls back to a lightweight heuristic (lower quality).

