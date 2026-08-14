import json
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

import config

HEADERS = {"User-Agent": config.USER_AGENT}

# Surrey Rec's site, and everyone using this bot, thinks in Pacific time —
# the server running this code doesn't necessarily (Fly's VMs run UTC), so
# every "today" comparison must be anchored to this explicitly rather than
# the host machine's system clock/timezone.
SITE_TIMEZONE = ZoneInfo("America/Vancouver")


def site_today():
    """Today's date in Surrey's local timezone, regardless of what
    timezone the machine running this code is in."""
    return datetime.now(SITE_TIMEZONE).date()


def build_search_url(
    base_url: str, lookahead_days: int, age_groups: list[str] | None = None
) -> str:
    """Return base_url with its `dates` query param replaced by a rolling
    window from today through today + lookahead_days. If age_groups is
    given, it replaces the `age_groups` query param too (repeated-param
    form, e.g. age_groups=youth&age_groups=adult — the site's comma-joined
    form silently resets the filter instead of combining values)."""
    start = site_today()
    end = start + timedelta(days=lookahead_days)
    date_range = f"{start.isoformat()}/{end.isoformat()}"

    parts = urlsplit(base_url)
    query = parse_qs(parts.query)
    query["dates"] = [date_range]
    if age_groups is not None:
        query["age_groups"] = age_groups
    new_query = urlencode(query, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def is_within_window(session: dict, window: timedelta) -> bool:
    """Whether a session's start_date falls between today and today + window."""
    try:
        start = datetime.strptime(session["start_date"], "%Y-%m-%d").date()
    except ValueError:
        return False
    today = site_today()
    return today <= start <= today + window


def fetch_listing(search_url: str) -> list[dict]:
    """Fetch the Surrey Recreation search-results page and return one dict per drop-in session."""
    resp = requests.get(search_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    sessions = []
    for date_block in soup.select("details.dropins-date"):
        date_id = date_block.get("id", "")
        for event in date_block.select(".dropins-event"):
            link = event.select_one(".dropins-event-button a")
            if not link or not link.get("href"):
                continue
            href = link["href"]
            class_id = re.search(r"classId=([a-f0-9-]{36})", href)
            widget_id = re.search(r"widgetId=([a-f0-9-]{36})", href)
            occurrence_date = re.search(r"occurrenceDate=(\d{8})", href)
            if not (class_id and widget_id and occurrence_date):
                continue

            subject = event.select_one(".dropins-event-subject")
            location = event.select_one(".dropins-event-location")
            time_range = event.select_one(".dropins-event-time-range")

            sessions.append(
                {
                    "class_id": class_id.group(1),
                    "widget_id": widget_id.group(1),
                    "occurrence_date": occurrence_date.group(1),
                    "date_id": date_id,
                    "activity_name": subject.get_text(strip=True) if subject else "",
                    "location": location.get_text(strip=True) if location else "",
                    "time_range": time_range.get_text(strip=True) if time_range else "",
                    "spots_left": int(event.get("data-spots", -1)),
                    "start_date": event.get("data-startdate", ""),
                    "detail_url": href.replace("&amp;", "&"),
                }
            )
    return sessions


def _extract_balanced_json(text: str, start_idx: int) -> str | None:
    """Given text and the index of an opening '{', return the substring of the
    balanced JSON object, respecting quoted strings and escape characters."""
    depth = 0
    in_string = False
    escape = False
    for i in range(start_idx, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start_idx : i + 1]
    return None


def fetch_session_detail(detail_url: str) -> dict:
    """Fetch a PerfectMind class landing page and return its embedded session data
    (MaximumCapacity, SpotsLeft, registration dates, IsFull, etc.)."""
    resp = requests.get(detail_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    text = resp.text

    marker = '{"ParentEventId":'
    idx = text.find(marker)
    if idx == -1:
        raise ValueError(f"Could not find session data in {detail_url}")

    blob = _extract_balanced_json(text, idx)
    if blob is None:
        raise ValueError(f"Could not parse balanced JSON in {detail_url}")

    return json.loads(blob)
