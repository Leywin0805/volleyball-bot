from datetime import datetime, timedelta

import config
import notifier
import scraper
import state as state_mod


RECENT_FILLS_KEPT = 4


def prune_old_occurrences(state: dict) -> None:
    """Drop stale notified-occurrence entries, and finalize any occurrence
    whose date has passed into the class's recent_fills history (so next
    week's run can check "did the corresponding occurrence one week ago
    fill up")."""
    today_str = scraper.site_today().strftime("%Y%m%d")
    for entry in state["classes"].values():
        entry["notified_occurrences"] = [
            d for d in entry["notified_occurrences"] if d >= today_str
        ]

        observed_fill = entry.get("observed_fill", {})
        recent_fills = entry.setdefault("recent_fills", [])
        for occurrence_date in [d for d in observed_fill if d < today_str]:
            recent_fills.append(
                {
                    "occurrence_date": occurrence_date,
                    "max_filled_ratio": observed_fill.pop(occurrence_date),
                }
            )
        if len(recent_fills) > RECENT_FILLS_KEPT:
            del recent_fills[: len(recent_fills) - RECENT_FILLS_KEPT]


def class_is_popular(entry: dict, occurrence_date: str) -> bool:
    """True if the same class's occurrence exactly one week before this one
    filled to at least POPULAR_FILL_RATIO. If there's no recorded occurrence
    for exactly one week prior (e.g. a holiday break skipped that week),
    this returns False rather than falling back to older data."""
    try:
        this_date = datetime.strptime(occurrence_date, "%Y%m%d").date()
    except ValueError:
        return False
    prior_week = (this_date - timedelta(days=7)).strftime("%Y%m%d")
    for record in entry.get("recent_fills", []):
        if record["occurrence_date"] == prior_week:
            return record["max_filled_ratio"] >= config.POPULAR_FILL_RATIO
    return False


def session_start_at(session: dict) -> datetime | None:
    """Timezone-aware start datetime (site time) from start_date + the
    start of time_range ("7:30pm - 9:30pm")."""
    try:
        day = datetime.strptime(session["start_date"], "%Y-%m-%d").date()
        start_str = session["time_range"].split("-")[0].strip().lower()
        t = datetime.strptime(start_str, "%I:%M%p").time()
    except (ValueError, KeyError, IndexError):
        return None
    return datetime.combine(day, t, tzinfo=scraper.SITE_TIMEZONE)


def registration_opens_at(session: dict) -> datetime | None:
    """Registration opens exactly REGISTRATION_OPENS_HOURS_BEFORE the session starts."""
    start = session_start_at(session)
    if start is None:
        return None
    return start - timedelta(hours=config.REGISTRATION_OPENS_HOURS_BEFORE)


def format_preopen_message(session: dict, opens_at: datetime) -> str:
    try:
        dt = datetime.strptime(session["start_date"], "%Y-%m-%d")
        friendly_date = f"{dt.strftime('%A, %b')} {dt.day}"
    except ValueError:
        friendly_date = session["start_date"]
    opens_str = opens_at.strftime("%I:%M%p").lstrip("0").lower()
    return (
        f"\u23f0 **{session['activity_name']}** at {session['location']} opens for "
        f"registration in {config.PREOPEN_LEAD_MINUTES} min (at {opens_str}) — this one "
        f"filled up last week, be ready! — {friendly_date}, {session['time_range']}\n"
        f"{session['detail_url']}"
    )


def find_preopen_alerts(state: dict, sessions: list[dict], horizon: timedelta) -> list[dict]:
    """Popular occurrences whose registration hasn't opened yet and whose
    heads-up time (opens_at - PREOPEN_LEAD_MINUTES) falls before now + horizon."""
    now = datetime.now(scraper.SITE_TIMEZONE)
    lead = timedelta(minutes=config.PREOPEN_LEAD_MINUTES)
    alerts = []
    for session in sessions:
        entry = state["classes"].get(session["class_id"])
        if entry is None:
            continue
        occurrence_date = session["occurrence_date"]
        if occurrence_date in entry["notified_occurrences"]:
            continue
        if not class_is_popular(entry, occurrence_date):
            continue
        opens_at = registration_opens_at(session)
        if opens_at is None or opens_at <= now:
            continue
        fire_at = opens_at - lead
        if fire_at <= now + horizon:
            alerts.append(
                {
                    "class_id": session["class_id"],
                    "occurrence_date": occurrence_date,
                    "fire_at": fire_at,
                    "message": format_preopen_message(session, opens_at),
                }
            )
    return alerts


def send_preopen_alert(alert: dict) -> None:
    """Send a scheduled heads-up and mark the occurrence notified, so the
    "just opened" alert doesn't also fire for it."""
    state = state_mod.load(config.STATE_FILE)
    entry = state_mod.get_class_entry(state, alert["class_id"])
    if alert["occurrence_date"] in entry["notified_occurrences"]:
        return
    print(f"  Pre-open notifying: {alert['message']}")
    notifier.notify(
        config.DISCORD_BOT_TOKEN,
        alert["message"],
        config.DISCORD_USER_ID,
        config.DISCORD_CHANNEL_ID,
        ping_everyone=True,
    )
    entry["notified_occurrences"].append(alert["occurrence_date"])
    state_mod.save(config.STATE_FILE, state)


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


def format_popular_open_message(
    session: dict, spots_left: int | None, max_capacity: int | None
) -> str:
    try:
        dt = datetime.strptime(session["start_date"], "%Y-%m-%d")
        friendly_date = f"{dt.strftime('%A, %b')} {dt.day}"
    except ValueError:
        friendly_date = session["start_date"]

    spots_note = (
        f" ({spots_left}/{max_capacity} spots open)"
        if max_capacity and spots_left is not None
        else ""
    )
    return (
        f"\U0001f525 **{session['activity_name']}** at {session['location']} just opened "
        f"for registration{spots_note} — this one filled up fast last week, grab a spot now! "
        f"— {friendly_date}, {session['time_range']}\n{session['detail_url']}"
    )


def run_check(state: dict, preopen_horizon: timedelta) -> list[dict]:
    """Fetch the listing, notify on any newly-half-full near-term session,
    and persist state. Returns pre-open heads-up alerts due within
    preopen_horizon for the caller to schedule at their exact fire_at."""
    prune_old_occurrences(state)

    search_url = scraper.build_search_url(config.SEARCH_URL_BASE, config.LOOKAHEAD_DAYS)
    sessions = scraper.fetch_listing(search_url)
    print(f"Fetched {len(sessions)} upcoming drop-in sessions")

    near_term = [
        s
        for s in sessions
        if scraper.is_within_window(s, timedelta(days=config.NOTIFY_WINDOW_DAYS))
    ]
    print(
        f"{len(near_term)} session(s) within the {config.NOTIFY_WINDOW_DAYS}-day "
        "notify window; checking their live registration status"
    )

    for session in near_term:
        class_id = session["class_id"]
        occurrence_date = session["occurrence_date"]
        entry = state_mod.get_class_entry(state, class_id)
        already_notified = occurrence_date in entry["notified_occurrences"]
        observed_fill = entry.setdefault("observed_fill", {})

        # Once we've seen a full occurrence, its outcome can't change —
        # skip re-fetching it for the rest of the week.
        if already_notified and observed_fill.get(occurrence_date) == 1.0:
            continue

        try:
            detail = scraper.fetch_session_detail(session["detail_url"])
        except Exception as exc:
            print(f"  Skipping {class_id}/{occurrence_date}: {exc}")
            continue

        max_capacity = detail.get("MaximumCapacity")
        spots_left = detail.get("SpotsLeft")
        filled_ratio = None
        if max_capacity and spots_left is not None:
            filled_ratio = (max_capacity - spots_left) / max_capacity
            observed_fill[occurrence_date] = max(
                observed_fill.get(occurrence_date, 0.0), filled_ratio
            )

        if already_notified:
            continue

        registration_open = not detail.get("IsFutureRegistration", True) and not detail.get(
            "IsRegistrationClosed", True
        )
        if not registration_open:
            continue

        popular = class_is_popular(entry, occurrence_date)
        should_notify = popular or (
            filled_ratio is not None and filled_ratio >= config.HALF_FULL_RATIO
        )

        if should_notify:
            if popular:
                message = format_popular_open_message(session, spots_left, max_capacity)
            else:
                message = format_message(session, spots_left, max_capacity)
            print(f"  Notifying: {message}")
            notifier.notify(
                config.DISCORD_BOT_TOKEN,
                message,
                config.DISCORD_USER_ID,
                config.DISCORD_CHANNEL_ID,
                ping_everyone=popular,
            )
            entry["notified_occurrences"].append(occurrence_date)

    state_mod.save(config.STATE_FILE, state)
    return find_preopen_alerts(state, sessions, preopen_horizon)
