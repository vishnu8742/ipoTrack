from __future__ import annotations

import os
import re
from typing import Any, Dict

import requests

from discord_notify import build_discord_payload


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _discord_markdown_to_plain(value: str) -> str:
    text = value
    text = text.replace("```json", "").replace("```", "")
    text = text.replace("**", "")
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return text.strip()


def build_telegram_message(track_payload: Dict[str, Any]) -> str:
    discord_payload = build_discord_payload(track_payload)
    embeds = discord_payload.get("embeds", []) or []
    if not embeds:
        return "IPO update unavailable."

    embed = embeds[0]
    title = str(embed.get("title", "IPO Update"))
    description = str(embed.get("description", "")).strip()
    fields = embed.get("fields", []) or []

    lines = [title]
    if description:
        lines.extend(["", description])

    for field in fields:
        name = str(field.get("name", "")).strip()
        value = _discord_markdown_to_plain(str(field.get("value", "")).strip())
        if name:
            lines.extend(["", name])
        if value:
            lines.append(value)

    return _truncate("\n".join(lines).strip(), 3800)


def send_to_telegram(
    track_payload: Dict[str, Any],
    bot_token: str | None = None,
    chat_id: str | None = None,
) -> Dict[str, Any]:
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    target_chat = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    parse_mode = os.getenv("TELEGRAM_PARSE_MODE", "").strip()
    disable_preview = os.getenv("TELEGRAM_DISABLE_WEB_PREVIEW", "true").strip().lower() == "true"
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")
    if not target_chat:
        raise ValueError("TELEGRAM_CHAT_ID is not set")

    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: Dict[str, Any] = {
        "chat_id": target_chat,
        "text": build_telegram_message(track_payload),
        "disable_web_page_preview": disable_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    response = requests.post(api_url, json=payload, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(
            f"Telegram sendMessage failed with status {response.status_code}: {response.text[:500]}"
        )

    data = response.json()
    if not data.get("ok", False):
        raise RuntimeError(f"Telegram API returned not ok: {data}")

    return {
        "status": "sent",
        "http_status": response.status_code,
        "ipo_count": len(track_payload.get("ipos", []) or []),
    }
