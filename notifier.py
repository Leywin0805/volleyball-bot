import requests

API_BASE = "https://discord.com/api/v10"


def _headers(bot_token: str) -> dict:
    return {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
    }


def send_dm(bot_token: str, user_id: str, content: str) -> None:
    resp = requests.post(
        f"{API_BASE}/users/@me/channels",
        headers=_headers(bot_token),
        json={"recipient_id": user_id},
        timeout=15,
    )
    resp.raise_for_status()
    channel_id = resp.json()["id"]
    send_to_channel(bot_token, channel_id, content)


def send_to_channel(bot_token: str, channel_id: str, content: str) -> None:
    resp = requests.post(
        f"{API_BASE}/channels/{channel_id}/messages",
        headers=_headers(bot_token),
        json={"content": content},
        timeout=15,
    )
    resp.raise_for_status()


def notify(bot_token: str, content: str, user_id: str | None, channel_id: str | None) -> None:
    if user_id:
        send_dm(bot_token, user_id, content)
    if channel_id:
        send_to_channel(bot_token, channel_id, content)
