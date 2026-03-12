# IPO Track API

Simple Flask API to:

- fetch active IPOs from NSE
- scrape GMP from Chittorgarh and IPOWatch
- fetch gold price from Safegold
- compute GMP percent
- return cleaned JSON
- send formatted updates to Discord
- send formatted updates to Telegram

## Endpoints

- `GET /track`
  - Returns current IPO tracking payload.

- `POST /track/notify-discord`
  - Builds payload and sends to Discord webhook.
  - Protected by local-IP/token checks.

- `POST /track/notify-telegram`
  - Builds payload and sends to Telegram bot chat.
  - Protected by local-IP/token checks.

## Response format (`/track`)

```json
{
  "date": "26 Feb 2026",
  "gold_price": {
    "source": "safegold",
    "buy_price_per_gram": 7125.5,
    "sell_price_per_gram": 7050.25,
    "currency": "INR",
    "as_of": "2026-02-26T09:20:00+00:00"
  },
  "ipos": [
    {
      "ipo_name": "PNGS Reva Diamond Jewellery Limited",
      "subscription_window": "24 Feb 2026 – 26 Feb 2026",
      "gmp_percent": 3.9,
      "action": "AVOID",
      "reason": "Low GMP around 4% and moderate subscription."
    }
  ]
}
```

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create env file:
```bash
cp .env.example .env
```

3. Fill `.env` values.

4. Run server:
```bash
python3 app.py
```

Default app port is `8001`.

## Environment variables

- `DISCORD_WEBHOOK_URL`: Discord incoming webhook URL
- `TELEGRAM_BOT_TOKEN`: Telegram bot token from BotFather
- `TELEGRAM_CHAT_ID`: destination chat ID (user/group/channel)
- `TELEGRAM_PARSE_MODE`: optional parse mode (`Markdown`, `HTML`, or empty)
- `TELEGRAM_DISABLE_WEB_PREVIEW`: `true`/`false` (default `true`)
- `SAFEGOLD_POST_RATE_URL`: Safegold POST endpoint returning JWT rate blob
- `SAFEGOLD_TID_URL`: endpoint used to fetch CSRF/tid token (`/get-tid`)
- `SAFEGOLD_CSRF`: optional override token (if empty, app fetches from `SAFEGOLD_TID_URL`)
- `SAFEGOLD_UPI`: header value for Safegold POST endpoint (default `0`)
- `TRACK_NOTIFY_TOKEN`: secret token for manual/external triggering
- `TRACK_NOTIFY_ALLOW_IPS`: comma-separated allowed IPs (non-loopback)
- `TRUST_PROXY_HEADERS`: `true`/`false` (default `false`)
- `TRUSTED_PROXY_IPS`: comma-separated proxy IPs (used only when trust is enabled)

## Auth behavior for notify endpoints

- Always allows loopback (`127.0.0.1`, `::1`) for local cron.
- Allows IPs listed in `TRACK_NOTIFY_ALLOW_IPS`.
- Allows requests with:
  - `X-Track-Token: <TRACK_NOTIFY_TOKEN>`, or
  - `Authorization: Bearer <TRACK_NOTIFY_TOKEN>`

## Cron example (trigger API only)

```cron
50 9 * * * curl -fsS -X POST http://127.0.0.1:8001/track/notify-discord >> /var/log/ipo_track_cron.log 2>&1
0 15 * * * curl -fsS -X POST http://127.0.0.1:8001/track/notify-discord >> /var/log/ipo_track_cron.log 2>&1

# Telegram (optional, separate trigger)
50 9 * * * curl -fsS -X POST http://127.0.0.1:8001/track/notify-telegram >> /var/log/ipo_track_cron.log 2>&1
0 15 * * * curl -fsS -X POST http://127.0.0.1:8001/track/notify-telegram >> /var/log/ipo_track_cron.log 2>&1
```

## Notes

- Keep `.env` private (already git-ignored).
- If any secret was exposed, rotate it immediately.

## If you just want IPO & Gold Rate updates
- Just Join Discord Channel: https://discord.gg/EayyBFjzdw
- Just Join Telegram Channel: https://t.me/ipoTrackUpdates
