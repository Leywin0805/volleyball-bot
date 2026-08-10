# volleyball-bot

A Discord bot that watches the City of Surrey Recreation drop-in volleyball
listings. It runs continuously in your server and does two things:

- **Pings you** once a session's registration fills to half capacity (configurable) —
  or immediately when registration opens for a session that's historically popular
  (see below), since those can fill up long before hitting 50%.
- **Answers `/48`** on demand — lists every drop-in volleyball session (Youth
  13-18 and Adult) starting in the next 48 hours, since browsing Surrey's own
  site for this is slow.

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
5. Every occurrence's peak `filled_ratio` gets recorded once its date passes
   (`recent_fills` in `state.json`, per class). Each recurring weekly class
   (same `class_id` every week, e.g. "Monday 5:15pm Guildford 13+") is
   checked against **the occurrence exactly one week before the one it's
   currently evaluating** — if that hit `POPULAR_FILL_RATIO` (default 0.8),
   the class is "popular" and gets notified **the moment registration opens**
   (bounded by `WATCH_INTERVAL_MINUTES`, not truly instant) instead of
   waiting for `HALF_FULL_RATIO`. If there's no occurrence recorded for
   exactly one week prior — a holiday break skipped that week, or it's a
   brand new class the bot hasn't seen before — this is skipped and the
   class falls back to normal `HALF_FULL_RATIO` behavior for that week.

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Fill in `.env`:

- `SURREY_SEARCH_URL` — paste the URL from Surrey's site after picking your
  filters (age group, locations, activity). The `dates` (and, for `/48`, the
  `age_groups`) parts are replaced automatically at runtime.
- `DISCORD_BOT_TOKEN`, `DISCORD_USER_ID`, and/or `DISCORD_CHANNEL_ID` — see
  below.
- `DISCORD_GUILD_ID` — optional, speeds up slash-command syncing while you're
  developing (see below).

Run it:

```bash
python bot.py
```

This starts the bot as a long-running process: it logs into Discord, starts
answering `/48`, and runs the half-full watch loop every
`WATCH_INTERVAL_MINUTES` (default 15) in the background. Leave it running —
for always-on hosting see **Deploying** below.

## Setting up the Discord bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   → **New Application**.
2. **Bot** tab → **Reset Token** → copy it into `DISCORD_BOT_TOKEN`. Keep this
   secret. No privileged intents are needed (slash commands don't require
   message content).
3. **OAuth2 → URL Generator**: check scopes `bot` **and** `applications.commands`
   (the second one is required for slash commands like `/48` to work), and
   under bot permissions check `Send Messages`, `Embed Links`. Open the
   generated URL and invite the bot to your server.
4. To also have it **DM you** for half-full alerts: copy your user ID
   (right-click your name → Copy User ID, with Developer Mode on) →
   `DISCORD_USER_ID`. To post those alerts in a **channel** instead/as well,
   right-click the channel → Copy Channel ID → `DISCORD_CHANNEL_ID`.
5. While developing, set `DISCORD_GUILD_ID` (right-click your server icon →
   Copy Server ID) so `/48` registers instantly in that one server. Without
   it, commands sync globally, which can take up to an hour to show up.

## Using `/48`

Run `/48` in any channel the bot can see. It lists every drop-in volleyball
session (Youth 13-18 and Adult) starting in the next 48 hours, grouped by
day, with live spot counts where the registration window has actually opened
(same `NOTIFY_WINDOW_DAYS` reliability rule as the watch loop — see below).

## Deploying (Fly.io)

The bot needs to run 24/7 to answer commands and keep watching, so it's no
longer a GitHub Actions cron job — it's a persistent process. This repo
includes a `Dockerfile` and `fly.toml` set up for [Fly.io](https://fly.io),
which has a free allowance that comfortably covers a bot this light.

1. [Install flyctl](https://fly.io/docs/flyctl/install/) and `fly auth login`.
2. From this directory: `fly launch --no-deploy` — it'll detect the
   `Dockerfile`/`fly.toml`, ask you to confirm (or pick a new) app name since
   app names are globally unique, and create a volume for you (or run
   `fly volumes create volleyball_data --size 1` yourself first).
3. Set secrets (nothing in `.env` gets committed or baked into the image):
   ```bash
   fly secrets set DISCORD_BOT_TOKEN=... SURREY_SEARCH_URL=... DISCORD_USER_ID=... DISCORD_CHANNEL_ID=...
   ```
4. `fly deploy`.
5. Check it came up: `fly logs` should show `Logged in as ...` and a command
   sync line. The bot should now show Online in Discord continuously.

`state.json` lives on the mounted Fly volume (`/data`, set via `STATE_FILE`
in `fly.toml`), so it survives redeploys instead of needing to be committed
back to git the way the old GitHub Actions version did.

## Files

- `scraper.py` — fetches and parses the listing + detail pages
- `state.py` — tracks per-class capacity and which occurrences were already notified
- `notifier.py` — sends Discord DMs/channel messages via the bot REST API
- `watcher.py` — one check-and-notify cycle (the half-full watch logic)
- `bot.py` — persistent Discord client: registers `/48`, runs the watch loop
  on a timer
- `Dockerfile`, `fly.toml`, `.dockerignore` — Fly.io deployment
