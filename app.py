import logging
import os

from flask import Flask, jsonify

from discord_notify import send_to_discord
from track_pipeline import build_track_payload

# configure logging for the application
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.get("/track")
def track():
    logger.debug("Received request for /track endpoint")
    payload = build_track_payload()
    logger.debug("Track payload built: %s", payload)
    return jsonify(payload)


@app.post("/track/notify-discord")
def track_notify_discord():
    logger.debug("Received request for /track/notify-discord endpoint")
    payload = build_track_payload()
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    result = send_to_discord(payload, webhook_url=webhook_url)
    return jsonify({"status": "ok", "discord": result, "payload": payload})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
