# IPO Track API

Simple Flask API to:

- fetch active IPOs from NSE
- scrape GMP from Chittorgarh and IPOWatch
- compute GMP percent
- return cleaned JSON
- send formatted updates to Discord

## Endpoints

- `GET /track`
  - Returns current IPO tracking payload.

- `POST /track/notify-discord`
  - Builds payload and sends to Discord webhook.
  - Protected by local-IP/token checks.

## Response format (`/track`)

```json
{
  "date": "26 Feb 2026",
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
- `TRACK_NOTIFY_TOKEN`: secret token for manual/external triggering
- `TRACK_NOTIFY_ALLOW_IPS`: comma-separated allowed IPs (non-loopback)
- `TRUST_PROXY_HEADERS`: `true`/`false` (default `false`)
- `TRUSTED_PROXY_IPS`: comma-separated proxy IPs (used only when trust is enabled)

## Auth behavior for `/track/notify-discord`

- Always allows loopback (`127.0.0.1`, `::1`) for local cron.
- Allows IPs listed in `TRACK_NOTIFY_ALLOW_IPS`.
- Allows requests with:
  - `X-Track-Token: <TRACK_NOTIFY_TOKEN>`, or
  - `Authorization: Bearer <TRACK_NOTIFY_TOKEN>`

## Cron example (trigger API only)

```cron
50 9 * * * curl -fsS -X POST http://127.0.0.1:8001/track/notify-discord >> /var/log/ipo_track_cron.log 2>&1
0 15 * * * curl -fsS -X POST http://127.0.0.1:8001/track/notify-discord >> /var/log/ipo_track_cron.log 2>&1
```

## Notes

- Keep `.env` private (already git-ignored).
- If any secret was exposed, rotate it immediately.

## If you just want IPO updates
- Just Join Discord Channel: https://discord.gg/EayyBFjzdw
