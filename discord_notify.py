from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import requests


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _render_summary_lines(ipos: List[Dict[str, Any]]) -> str:
    lines = []
    for idx, ipo in enumerate(ipos, 1):
        reason = ipo.get("reason", "")
        window = ipo.get("subscription_window", "N/A")
        lines.append(
            f"{idx}. {ipo.get('ipo_name', 'Unknown')} | Window: {window} | "
            f"GMP: {ipo.get('gmp_percent', 0)}% | {ipo.get('action', 'WATCH')} | Reason: {reason}"
        )
    return "\n".join(lines)


def build_discord_payload(track_payload: Dict[str, Any]) -> Dict[str, Any]:
    date_text = track_payload.get("date", "")
    ipos = track_payload.get("ipos", []) or []

    title = f"IPO Track Update - {date_text}" if date_text else "IPO Track Update"
    summary = "No active IPO entries with GMP match found."
    if ipos:
        summary = _render_summary_lines(ipos)

    pretty_json = json.dumps(track_payload, indent=2)
    if len(pretty_json) > 1500:
        pretty_json = pretty_json[:1497] + "..."

    fields = [
        {
            "name": "Summary",
            "value": _truncate(summary, 1024),
            "inline": False,
        },
        {
            "name": "Payload",
            "value": _truncate(f"```json\n{pretty_json}\n```", 1024),
            "inline": False,
        },
    ]

    embed = {
        "title": title,
        "description": f"Active IPOs with GMP insights: **{len(ipos)}**",
        "color": 3447003,
        "fields": fields,
    }

    return {
        "content": "Daily IPO tracker update",
        "embeds": [embed],
    }


def send_to_discord(track_payload: Dict[str, Any], webhook_url: str | None = None) -> Dict[str, Any]:
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        raise ValueError("DISCORD_WEBHOOK_URL is not set")

    payload = build_discord_payload(track_payload)
    response = requests.post(url, json=payload, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(
            f"Discord webhook failed with status {response.status_code}: {response.text[:500]}"
        )

    return {
        "status": "sent",
        "http_status": response.status_code,
        "ipo_count": len(track_payload.get("ipos", []) or []),
    }
