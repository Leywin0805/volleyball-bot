import sys
import traceback
from datetime import datetime, timedelta

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import discord
from discord import app_commands
from discord.ext import tasks

import config
import scraper
import state as state_mod
import watcher

AGE_GROUPS_48H = ["youth", "adult"]
WINDOW_48H = timedelta(hours=48)

# The site's age_groups query param doesn't actually narrow drop-in
# volleyball results (confirmed live: youth+adult and adult-alone both
# return the same 388 sessions, including "Family" ones) — so filter by the
# activity's own label instead, to match what the user actually asked for.
TARGET_LABELS = ("13+", "Adult")


def matches_target_age_group(session: dict) -> bool:
    return any(label in session["activity_name"] for label in TARGET_LABELS)


def parse_start_time(time_range: str) -> datetime | None:
    """Pull the start time out of a "5:15pm - 6:45pm" range, for sorting
    same-day sessions chronologically."""
    start_str = time_range.split("-")[0].strip()
    try:
        return datetime.strptime(start_str, "%I:%M%p")
    except ValueError:
        return None


def describe_spots(detail: dict | None) -> str:
    if detail is None:
        return ""
    max_capacity = detail.get("MaximumCapacity")
    spots_left = detail.get("SpotsLeft")
    if max_capacity and spots_left is not None:
        return f" — {spots_left}/{max_capacity} spots left"
    if detail.get("IsFutureRegistration"):
        return " — registration not open yet"
    if detail.get("IsRegistrationClosed"):
        return " — registration closed"
    return ""


def build_48h_embed(sessions: list[dict], details_by_key: dict[str, dict]) -> discord.Embed:
    embed = discord.Embed(
        title="\U0001f3d0 Drop-in volleyball — next 48 hours",
        color=discord.Color.orange(),
    )

    by_date: dict[str, list[dict]] = {}
    for s in sessions:
        by_date.setdefault(s["start_date"], []).append(s)

    for start_date in sorted(by_date):
        day_sessions = sorted(
            by_date[start_date],
            key=lambda s: parse_start_time(s["time_range"]) or datetime.min,
        )
        dt = datetime.strptime(start_date, "%Y-%m-%d")
        header = f"{dt.strftime('%A, %b')} {dt.day}"

        lines = []
        for s in day_sessions:
            key = f"{s['class_id']}:{s['occurrence_date']}"
            spots_note = describe_spots(details_by_key.get(key))
            lines.append(
                f"**{s['time_range']}** — {s['activity_name']} @ {s['location']}"
                f"{spots_note}\n[Register]({s['detail_url']})"
            )
        embed.add_field(name=header, value="\n\n".join(lines), inline=False)

    return embed


class VolleyballClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        if config.DISCORD_GUILD_ID:
            guild = discord.Object(id=int(config.DISCORD_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Synced commands to guild {config.DISCORD_GUILD_ID}")
        else:
            await self.tree.sync()
            print("Synced commands globally (may take up to an hour to appear)")
        self.watch_loop.start()

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user} (id={self.user.id})")

    @tasks.loop(minutes=config.WATCH_INTERVAL_MINUTES)
    async def watch_loop(self) -> None:
        try:
            state = state_mod.load(config.STATE_FILE)
            watcher.run_check(state)
        except Exception:
            traceback.print_exc()

    @watch_loop.before_loop
    async def before_watch_loop(self) -> None:
        await self.wait_until_ready()


client = VolleyballClient()


@client.tree.command(
    name="48",
    description="List drop-in volleyball sessions (13+ and Adult) in the next 48 hours",
)
async def forty_eight(interaction: discord.Interaction) -> None:
    if config.DISCORD_CHANNEL_ID and str(interaction.channel_id) != config.DISCORD_CHANNEL_ID:
        await interaction.response.send_message(
            f"Use this in <#{config.DISCORD_CHANNEL_ID}> instead.", ephemeral=True
        )
        return

    await interaction.response.defer()

    try:
        search_url = scraper.build_search_url(
            config.SEARCH_URL_BASE, lookahead_days=2, age_groups=AGE_GROUPS_48H
        )
        sessions = scraper.fetch_listing(search_url)
        near_term = [
            s
            for s in sessions
            if scraper.is_within_window(s, WINDOW_48H) and matches_target_age_group(s)
        ]

        if not near_term:
            await interaction.followup.send(
                "No drop-in volleyball sessions found in the next 48 hours."
            )
            return

        reliable_window = timedelta(days=config.NOTIFY_WINDOW_DAYS)
        details_by_key: dict[str, dict] = {}
        for s in near_term:
            if not scraper.is_within_window(s, reliable_window):
                continue
            key = f"{s['class_id']}:{s['occurrence_date']}"
            try:
                details_by_key[key] = scraper.fetch_session_detail(s["detail_url"])
            except Exception as exc:
                print(f"  Could not fetch detail for {key}: {exc}")

        embed = build_48h_embed(near_term, details_by_key)
        await interaction.followup.send(embed=embed)
    except Exception:
        traceback.print_exc()
        await interaction.followup.send(
            "Something went wrong fetching sessions — check the bot logs."
        )


def main() -> None:
    client.run(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
