# Scroll Patrol 🚨

The internet's funniest posts, arrested hourly. A static page that tracks
trending posts, memes and viral chaos from public feeds (Reddit, meme-api,
Bluesky, Lemmy, JokeAPI) — no API keys, no logins.

- Private repo: precinct files (this repo's twin `scroll-patrol` stays private)
- Public host: https://bishowpratap7.github.io/scrollpatrol/
- Updates: GitHub Actions cron inside the public repo runs `tools/scan.py`
  twice an hour, bakes the latest haul into `index.html`, and commits only
  when the haul changed.
- Run by Bishow Pandey — follow the Chief on X: https://x.com/bishowppandey
