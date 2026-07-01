# Telegram Notifications Setup Guide

## Overview

Condo Charge Phase 6 adds Telegram notifications for:

- station available
- charging session completed
- agent offline
- agent recovered

Residents link their Telegram account from the resident profile page. The backend issues a one-time Telegram deep link token, and the Telegram bot webhook stores the resident `chat_id` after `/start <token>`.

## Environment Variables

Set these backend environment variables before deployment:

```bash
CONDOCHARGE_NOTIFICATIONS_ENABLED=true
CONDOCHARGE_TELEGRAM_BOT_TOKEN=<telegram-bot-token>
CONDOCHARGE_TELEGRAM_BOT_USERNAME=<bot-username-without-@>
CONDOCHARGE_TELEGRAM_WEBHOOK_SECRET=<long-random-secret>
CONDOCHARGE_TELEGRAM_LINK_TOKEN_TTL_MINUTES=30
CONDOCHARGE_TELEGRAM_REQUEST_TIMEOUT_SECONDS=10
CONDOCHARGE_TELEGRAM_AGENT_OFFLINE_THRESHOLD_SECONDS=180
```

Recommended:

- keep `CONDOCHARGE_PUBLIC_URL` set to the public HTTPS URL of the backend
- use a long random value for `CONDOCHARGE_TELEGRAM_WEBHOOK_SECRET`
- keep `CONDOCHARGE_NOTIFICATIONS_ENABLED=true` only when email/Telegram delivery is intended

## Database Migration

Run the latest Alembic migration:

```bash
cd backend
python -m alembic upgrade head
```

This migration adds:

- resident Telegram link metadata on `app_users`
- Telegram per-event toggles on `condominiums`
- resident agent notification preferences
- `resident_notification_history`
- `resident_telegram_link_tokens`

## Bot Creation

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather).
2. Run `/newbot`.
3. Save the bot token.
4. Set the bot username in `CONDOCHARGE_TELEGRAM_BOT_USERNAME`.

## Webhook Registration

After deployment, register the Telegram webhook:

```bash
curl -X POST "https://api.telegram.org/bot<token>/setWebhook" ^
  -H "Content-Type: application/json" ^
  -d "{\"url\":\"https://<your-backend-host>/api/v1/telegram/webhook\",\"secret_token\":\"<same-secret-as-CONDOCHARGE_TELEGRAM_WEBHOOK_SECRET>\"}"
```

Verify with:

```bash
curl "https://api.telegram.org/bot<token>/getWebhookInfo"
```

Expected webhook path:

```text
/api/v1/telegram/webhook
```

## Resident Linking Flow

1. Resident signs in to Condo Charge.
2. Resident opens `Profile`.
3. Resident clicks `Generate Telegram link`.
4. Condo Charge creates a one-time link token and shows the bot deep link.
5. Resident opens the bot link in Telegram.
6. Telegram sends `/start <token>` to the backend webhook.
7. Condo Charge stores:
   - `telegram_chat_id`
   - `telegram_username`
   - `telegram_linked_at`

Residents can unlink Telegram from the same profile page.

## Admin Configuration

Open `Admin Settings` and verify:

- Telegram bot status
- test Telegram delivery using a chat ID
- per-event enable/disable toggles:
  - station available
  - charging completed
  - agent offline
  - agent recovered

## Notification Behavior

- `charging_completed` is sent when a recent session import finishes for a linked resident.
- `station_available` is sent when a station transitions from a non-available state to `available`.
- `agent_offline` is sent when the latest agent heartbeat becomes older than the configured threshold.
- `agent_recovered` is sent when the agent returns online after an offline state.
- Telegram duplicates are blocked by a unique dedupe key in `resident_notification_history`.

## Validation Checklist

1. Open `Admin Settings` and confirm Telegram status is `ok`.
2. Send a Telegram test message to a known chat ID.
3. Link a resident account from the resident profile page.
4. Simulate or import a recent charging session and verify `charging_completed`.
5. Simulate a station transition to `available` and verify `station_available`.
6. Simulate stale heartbeat and recovery and verify `agent_offline` and `agent_recovered`.

## Troubleshooting

- `status=disabled`: bot token is missing.
- Webhook 403: `CONDOCHARGE_TELEGRAM_WEBHOOK_SECRET` does not match Telegram `secret_token`.
- Link failed: resident deep link token expired or was already used.
- No resident delivery: resident has no linked `chat_id`, or the event is disabled in resident/admin preferences.
- Repeated sends blocked: check `resident_notification_history` for an existing dedupe key.
