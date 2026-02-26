import logging
import os
import hmac
import ipaddress

from flask import Flask, jsonify, request

from discord_notify import send_to_discord
from track_pipeline import build_track_payload

# configure logging for the application
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)


def _client_ip() -> str:
    # Do not trust X-Forwarded-For by default (spoofable).
    client_ip = request.remote_addr or ""
    trust_proxy = os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() == "true"
    trusted_proxies = {
        x.strip() for x in os.getenv("TRUSTED_PROXY_IPS", "").split(",") if x.strip()
    }
    if trust_proxy and client_ip in trusted_proxies:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return client_ip


def _is_loopback(ip_text: str) -> bool:
    try:
        return ipaddress.ip_address(ip_text).is_loopback
    except ValueError:
        return False


def _is_notify_authorized() -> bool:
    client_ip = _client_ip()
    if _is_loopback(client_ip):
        return True

    allowed_ips = {x.strip() for x in os.getenv("TRACK_NOTIFY_ALLOW_IPS", "").split(",") if x.strip()}
    if client_ip and client_ip in allowed_ips:
        return True

    expected = os.getenv("TRACK_NOTIFY_TOKEN", "").strip()
    if not expected:
        return False

    provided = (request.headers.get("X-Track-Token") or "").strip()
    auth_header = (request.headers.get("Authorization") or "").strip()
    bearer = ""
    if auth_header.lower().startswith("bearer "):
        bearer = auth_header[7:].strip()

    return hmac.compare_digest(provided, expected) or hmac.compare_digest(bearer, expected)


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
    app.run(host="0.0.0.0", port=8001, debug=True)
