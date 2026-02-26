from __future__ import annotations

import json
import logging
import sys

from discord_notify import send_to_discord
from track_pipeline import build_track_payload

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    payload = build_track_payload()
    try:
        result = send_to_discord(payload)
    except Exception as exc:
        logger.exception("Failed to send Discord update: %s", exc)
        print(json.dumps({"status": "failed", "error": str(exc), "payload": payload}, indent=2))
        return 1

    print(json.dumps({"status": "ok", "discord": result, "payload": payload}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
