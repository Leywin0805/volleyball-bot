import sys
from datetime import date, datetime, timedelta

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import config
import notifier
import scraper
import state as state_mod


def prune_old_occurrences(state: dict) -> None:
    today_str = date.today().strftime("%Y%m%d")
    for entry in state["classes"].values():
        entry["notified_occurrences"] = [
            d for d in entry["notified_occurrences"] if d >= today_str
        ]


def is_near_term(session: dict, window_days: int) -> bool:
    """The listing page's spot counts are unreliable for occurrences whose
    registration hasn't opened yet (it just repeats a future/template number).
    Only sessions happening soon are worth fetching the authoritative detail
    page for."""
    try:
        start = datetime.strptime(session["start_date"], "%Y-%m-%d").date()
    except ValueError:
        return False
    today = date.today()
    return today <= start <= today + timedelta(days=window_days)


def format_message(session: dict, spots_left: int, max_capacity: int) -> str:
    taken = max_capacity - spots_left
    try:
        dt = datetime.strptime(session["start_date"], "%Y-%m-%d")
        friendly_date = f"{dt.strftime('%A, %b')} {dt.day}"
    except ValueError:
        friendly_date = session["start_date"]

    return (
        f"\U0001f3d0 **{session['activity_name']}** at {session['location']} is "
        f"half full! {taken}/{max_capacity} spots taken ({spots_left} left) "
        f"— {friendly_date}, {session['time_range']}\n{session['detail_url']}"
    )


def main() -> None:
    state = state_mod.load(config.STATE_FILE)
    prune_old_occurrences(state)

    search_url = scraper.build_search_url(config.SEARCH_URL_BASE, config.LOOKAHEAD_DAYS)
    sessions = scraper.fetch_listing(search_url)
    print(f"Fetched {len(sessions)} upcoming drop-in sessions")

    near_term = [s for s in sessions if is_near_term(s, config.NOTIFY_WINDOW_DAYS)]
    print(
        f"{len(near_term)} session(s) within the {config.NOTIFY_WINDOW_DAYS}-day "
        "notify window; checking their live registration status"
    )

    for session in near_term:
        class_id = session["class_id"]
        occurrence_date = session["occurrence_date"]
        entry = state_mod.get_class_entry(state, class_id)

        if occurrence_date in entry["notified_occurrences"]:
            continue

        try:
            detail = scraper.fetch_session_detail(session["detail_url"])
        except Exception as exc:
            print(f"  Skipping {class_id}/{occurrence_date}: {exc}")
            continue

        registration_open = not detail.get("IsFutureRegistration", True) and not detail.get(
            "IsRegistrationClosed", True
        )
        if not registration_open:
            continue

        max_capacity = detail.get("MaximumCapacity")
        spots_left = detail.get("SpotsLeft")
        if not max_capacity or spots_left is None:
            continue

        filled_ratio = (max_capacity - spots_left) / max_capacity

        if filled_ratio >= config.HALF_FULL_RATIO:
            message = format_message(session, spots_left, max_capacity)
            print(f"  Notifying: {message}")
            notifier.notify(
                config.DISCORD_BOT_TOKEN,
                message,
                config.DISCORD_USER_ID,
                config.DISCORD_CHANNEL_ID,
            )
            entry["notified_occurrences"].append(occurrence_date)

    state_mod.save(config.STATE_FILE, state)


if __name__ == "__main__":
    main()
