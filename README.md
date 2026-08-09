# volleyball-bot

Watches the City of Surrey Recreation drop-in volleyball listings and pings you on
Discord once a session's registration fills to half capacity (configurable).

## How it works

1. Fetches the Surrey Recreation search-results page (a plain HTTP GET — no
   headless browser needed) to get the full list of upcoming drop-in
   occurrences (class ID, date, location, time).
   **Note:** this listing page's `data-spots` count is *not* reliable for
   future occurrences of a recurring class — it repeats the same number
   across every future week rather than tracking each date independently, so
   it's only used to build the list, never to decide anything.
2. Filters that list down to sessions starting within `NOTIFY_WINDOW_DAYS`
   (default 3) — registration opens exactly 3 days before a session (verified
   against live data across multiple venues and both "13+" and "Adult"
   categories), so anything further out isn't worth checking yet.
3. For each near-term session, fetches its actual PerfectMind booking page,
   which has the authoritative per-occurrence `SpotsLeft`, `MaximumCapacity`,
   and whether registration has actually opened (`IsFutureRegistration` /
   `IsRegistrationClosed`).
4. Computes `filled_ratio = (capacity - spots_left) / capacity`. Once
   registration is open and that ratio crosses `HALF_FULL_RATIO` for a
   specific occurrence, it sends a Discord notification (DM and/or channel)
   and records that occurrence in `state.json` so it won't notify again for
   the same date.

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Fill in `.env`:

- `SURREY_SEARCH_URL` — paste the URL from Surrey's site after picking your
  filters (age group, locations, activity). The `dates` part is replaced
  automatically each run with a rolling `LOOKAHEAD_DAYS`-day window.
- `DISCORD_BOT_TOKEN`, `DISCORD_USER_ID`, and/or `DISCORD_CHANNEL_ID` — see
  below.

Run once:

```bash
python main.py
```

## Setting up the Discord bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   → **New Application**.
2. **Bot** tab → **Reset Token** → copy it into `DISCORD_BOT_TOKEN`. Keep this
   secret.
3. To post in a **channel**: use the OAuth2 URL Generator (scope `bot`,
   permission `Send Messages`) to invite the bot to your server, then right
   click the target channel → Copy Channel ID (enable Developer Mode in
   Discord settings first) → `DISCORD_CHANNEL_ID`.
4. To **DM you directly**: the bot needs to share a server with you (inviting
   it to any server you're in is enough). Copy your user ID (right-click your
   name → Copy User ID) → `DISCORD_USER_ID`.
5. You can set both `DISCORD_USER_ID` and `DISCORD_CHANNEL_ID` to get both.

## Deploying on a schedule (GitHub Actions — free)

This repo includes `.github/workflows/check.yml`, which runs every 15 minutes.

1. Push this project to a **private** GitHub repo (it will be committing
   `state.json` back on every run, and your search URL/IDs, while not secret,
   don't need to be public).
2. Repo **Settings → Secrets and variables → Actions**:
   - **Secrets**: add `DISCORD_BOT_TOKEN`.
   - **Variables**: add `SURREY_SEARCH_URL`, `DISCORD_USER_ID` and/or
     `DISCORD_CHANNEL_ID`, and optionally `LOOKAHEAD_DAYS` /
     `NOTIFY_WINDOW_DAYS` / `HALF_FULL_RATIO`.
3. That's it — the workflow checks out the repo, runs `main.py`, and commits
   the updated `state.json` so it remembers what it already notified you
   about between runs.

You can lower the cron interval (e.g. `*/5 * * * *`) if you want faster
notifications right after registration opens, but be considerate of Surrey's
site — 15 minutes is already plenty responsive for a 2-day registration
window.

## Files

- `scraper.py` — fetches and parses the listing + detail pages
- `state.py` — tracks per-class capacity and which occurrences were already notified
- `notifier.py` — sends Discord DMs/channel messages via the bot REST API
- `main.py` — orchestrates a single check-and-notify run
