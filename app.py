import logging
import os

from flask import Flask, jsonify, request

from discord_notify import send_to_discord
from track_pipeline import build_track_payload

# configure logging for the application
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)


def _client_ip() -> str:
    # Respect forwarded header only when present; use first hop.
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def _is_notify_authorized() -> bool:
    client_ip = _client_ip()
    if client_ip in {"127.0.0.1", "::1", "localhost"}:
        return True

    expected = os.getenv("TRACK_NOTIFY_TOKEN", "").strip()
    if not expected:
        return False

    provided = (request.headers.get("X-Track-Token") or "").strip()
    auth_header = (request.headers.get("Authorization") or "").strip()
    bearer = ""
    if auth_header.lower().startswith("bearer "):
        bearer = auth_header[7:].strip()

    return provided == expected or bearer == expected


@app.get("/track")
def track():
    logger.debug("Received request for /track endpoint")
    payload = build_track_payload()
    logger.debug("Track payload built: %s", payload)
    return jsonify(payload)


@app.post("/track/notify-discord")
def track_notify_discord():
    logger.debug("Received request for /track/notify-discord endpoint")
    if not _is_notify_authorized():
        logger.warning("Unauthorized notify attempt from ip=%s", _client_ip())
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    payload = build_track_payload()
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    result = send_to_discord(payload, webhook_url=webhook_url)
    return jsonify({"status": "ok", "discord": result, "payload": payload})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
