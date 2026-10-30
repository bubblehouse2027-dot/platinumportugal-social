# PLATINUM Portugal · social publisher

Publishes the posts in `calendar.json` to Instagram and the Facebook Page at their Lisbon time.

- `docs/media/NN/` – the files of post NN (served by GitHub Pages)
- `calendar.json` – date, time, kind, caption, files, cover, hold flag per post
- `state/published.json` – what has been published (written by the workflow)
- `publisher/publish.py` – the publisher (modes: `check`, `dry-run`, `run`, `--only N`)
- `.github/workflows/publish.yml` – runs every 30 minutes; also from Actions → Publish scheduled posts → Run workflow (modes check, dry-run, only, run)

Pause a post: set `"hold": true` on it in `calendar.json`. Remove a post: delete it from `calendar.json`.
Setup: see the setup guide (Docs).
