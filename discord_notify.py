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


def _render_gold_line(gold_price: Dict[str, Any] | None) -> str:
    if not gold_price:
        return "Gold (Safegold): unavailable"
    ccy = gold_price.get("currency", "INR")
    buy = gold_price.get("buy_price_per_gram")
    sell = gold_price.get("sell_price_per_gram")
    as_of = gold_price.get("as_of", "")
    if sell is None:
        return f"Gold (Safegold): Buy {ccy} {buy}/g | As of {as_of}"
    return f"Gold (Safegold): Buy {ccy} {buy}/g | Sell {ccy} {sell}/g | As of {as_of}"

def build_discord_payload(track_payload: Dict[str, Any]) -> Dict[str, Any]:
    date_text = track_payload.get("date", "")
    ipos = track_payload.get("ipos", []) or []
    gold_price = track_payload.get("gold_price")

    fields = []

    # IPO fields
    for ipo in ipos:
        name = ipo.get("ipo_name", "Unknown IPO")
        window = ipo.get("subscription_window", "N/A")
        gmp = ipo.get("gmp_percent", "N/A")
        subs = ipo.get("subscription_percent", "N/A")
        inst_subs = ipo.get("institutional_subscription_percent", "N/A")
        action = ipo.get("action", "WATCH")
        reason = ipo.get("reason", "")

        value = (
            f"📅 **Window:** {window}\n"
            f"📈 **GMP:** {gmp}%\n"
            f"📊 **Subscription:** {subs}%\n"
            f"🏦 **Institutional:** {inst_subs}%\n"
            f"⚠️ **Action:** **{action}**\n\n"
            f"**Reason**\n{reason}"
        )

        fields.append({
            "name": f"🏢 {name}",
            "value": value,
            "inline": False
        })

    # Gold price
    if gold_price:
        buy = gold_price.get("buy_price_per_gram")
        sell = gold_price.get("sell_price_per_gram")
        as_of = gold_price.get("as_of", "")

        gold_value = (
            f"🪙 **Buy:** ₹{buy}/gram\n"
            f"💱 **Sell:** ₹{sell}/gram\n"
            f"🕒 **Time:** {as_of[:16].replace('T',' ')}"
        )

        fields.append({
            "name": "Gold Price (Safegold)",
            "value": gold_value,
            "inline": False
        })

    embed = {
        "title": f"📊 IPO & GoldTracker – {date_text}",
        "description": f"Active IPOs with GMP insights: **{len(ipos)}**",
        "color": 0x2E86DE,
        "fields": fields,
        "footer": {
            "text": "IPO Track Bot"
        }
    }

    return {
        "content": None,
        "embeds": [embed],
    }

# def build_discord_payload(track_payload: Dict[str, Any]) -> Dict[str, Any]:
    date_text = track_payload.get("date", "")
    ipos = track_payload.get("ipos", []) or []
    gold_price = track_payload.get("gold_price")

    title = f"IPO & Gold Track Update - {date_text}" if date_text else "IPO Track Update"
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
            "name": "Gold Price",
            "value": _truncate(_render_gold_line(gold_price), 1024),
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
