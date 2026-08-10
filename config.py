import os

from dotenv import load_dotenv

load_dotenv()

SEARCH_URL_BASE = os.environ["SURREY_SEARCH_URL"]
LOOKAHEAD_DAYS = int(os.environ.get("LOOKAHEAD_DAYS", "14"))

# Only sessions starting within this many days are checked against the
# authoritative per-occurrence detail page (registration opens 3 days before
# a session, so sessions further out aren't worth checking yet).
NOTIFY_WINDOW_DAYS = int(os.environ.get("NOTIFY_WINDOW_DAYS", "3"))

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_USER_ID = os.environ.get("DISCORD_USER_ID", "").strip() or None
DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "").strip() or None

# Guild to sync slash commands to instantly during development. Leave unset
# to sync globally instead (can take up to an hour to propagate).
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "").strip() or None

# How often the background half-full watch loop runs, in minutes.
WATCH_INTERVAL_MINUTES = int(os.environ.get("WATCH_INTERVAL_MINUTES", "15"))

HALF_FULL_RATIO = float(os.environ.get("HALF_FULL_RATIO", "0.5"))

# If a class's occurrence exactly one week before this one filled to at
# least this ratio, treat the class as "popular" and notify the moment
# registration opens instead of waiting for HALF_FULL_RATIO.
POPULAR_FILL_RATIO = float(os.environ.get("POPULAR_FILL_RATIO", "0.8"))

STATE_FILE = os.environ.get("STATE_FILE", "state.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
