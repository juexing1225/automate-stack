# Setup Guide: SaaS Churn Preventer & Usage Watchdog

Spot account drop-offs before users cancel and initiate proactive concierge retention.

## Configuration Table

Replace the placeholders in the workflows:

| Placeholder | Where to get it | Example |
| :--- | :--- | :--- |
| `YOUR_PRODUCT_ANALYTICS_API_KEY` | PostHog / Mixpanel / Resend API Key | `re_123456...` |
| `YOUR_SLACK_WEBHOOK_URL` | Slack App / Incoming Webhooks | `https://hooks.slack.com/services/T00/B00/XXXX` |
| `YOUR_SENDER_EMAIL` | Verified sender address in your mail provider | `founder@yourdomain.com` |
| `YOUR_NOTIFICATION_EMAIL` | Admin inbox for notification copies | `team@yourdomain.com` |

## Installation Steps

1. In n8n, import `n8n/churn-watchdog.json`.
2. Update `YOUR_PRODUCT_ANALYTICS_API_KEY` and `YOUR_SLACK_WEBHOOK_URL`.
3. Import `n8n/churn-outreach.json` and configure `YOUR_SENDER_EMAIL`, `YOUR_NOTIFICATION_EMAIL`, and `YOUR_SLACK_WEBHOOK_URL`.
4. Turn on the workflows to monitor weekly telemetry.
