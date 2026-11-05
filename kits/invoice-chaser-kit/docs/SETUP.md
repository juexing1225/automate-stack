# Setup Guide: Invoice Chaser Kit

Stop chasing late payments manually. Set up the strict 4-stage reminder ladder in 15 minutes.

## Configuration Table

Replace the placeholders in the imported workflows with your own credentials:

| Placeholder | Where to get it | Example |
| :--- | :--- | :--- |
| `YOUR_STRIPE_RESTRICTED_KEY` | Stripe Dashboard > Developers > API keys > Restricted key | `rk_live_51...` |
| `YOUR_EMAIL_API_KEY` | Resend / SendGrid / Postmark API Key | `re_123456789...` |
| `YOUR_SENDER_EMAIL` | Verified sender address in your email provider | `billing@yourdomain.com` |
| `YOUR_SLACK_WEBHOOK_URL` | Slack App / Incoming Webhooks | `https://hooks.slack.com/services/T00/B00/XXXX` |

## Restricted Key Walkthrough (Stripe)

To protect your Stripe account, **never use your secret key (`sk_live_...`)**. Create a read-only restricted key:

1. Log into your [Stripe Dashboard](https://dashboard.stripe.com/apikeys).
2. Click **Create restricted key**.
3. Name it `AutomateStack Invoice Chaser`.
4. Permissions required:
   - **Invoices**: `Read`
   - **Customers**: `Read`
   - All other permissions: `None`.
5. Click **Create key** and copy the generated `rk_live_...` key.

## Step-by-Step Installation

1. In n8n, click **Workflows** > **Import from File**.
2. Select `n8n/invoice-chaser.json`.
3. In **Fetch Open Invoices**, replace `YOUR_STRIPE_RESTRICTED_KEY`.
4. In **Dispatch Client Email**, replace `YOUR_EMAIL_API_KEY` and `YOUR_SENDER_EMAIL`.
5. In **Notify Slack Admin**, replace `YOUR_SLACK_WEBHOOK_URL`.
6. Import `n8n/invoice-report.json` and update `YOUR_STRIPE_RESTRICTED_KEY` and `YOUR_SLACK_WEBHOOK_URL`.
7. Once verified with test invoices, toggle **Active** to **ON**.
