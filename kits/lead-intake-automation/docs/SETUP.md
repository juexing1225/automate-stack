# Setup Guide: Lead Intake Automation Kit

Turn form fills into qualified pipeline in under 15 minutes.

## Configuration Table

Replace the placeholders in the imported workflows with your own endpoints:

| Placeholder | Where to get it | Example |
| :--- | :--- | :--- |
| `YOUR_SLACK_WEBHOOK_URL` | Slack App / Incoming Webhooks | `https://hooks.slack.com/services/T00/B00/XXXX` |
| `YOUR_CRM_OR_SHEET_WEBHOOK_URL` | Make/Zapier webhook, Airtable, or Google Sheets App Script URL | `https://hook.eu1.make.com/xxxx` |
| `YOUR_NOTIFICATION_EMAIL` | Your primary notification email | `founder@example.com` |

## Step-by-Step Installation

1. Open your n8n workspace.
2. Click **Workflows** > **Import from File**.
3. Select `n8n/lead-intake.json`. The workflow lands **inactive**.
4. Double-click the **Send Slack Alert** node and replace `YOUR_SLACK_WEBHOOK_URL` with your actual Slack webhook URL.
5. Double-click the **Forward to CRM** node and replace `YOUR_CRM_OR_SHEET_WEBHOOK_URL` and `YOUR_NOTIFICATION_EMAIL`.
6. Import `n8n/lead-intake-digest.json` and update `YOUR_SLACK_WEBHOOK_URL` and `YOUR_CRM_OR_SHEET_WEBHOOK_URL`.

## Copy-Paste Test Command

Run this `curl` command against your n8n test webhook URL to verify lead scoring and alert formatting:

```bash
curl -X POST "http://localhost:5678/webhook-test/lead-intake" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sarah Connor",
    "email": "sarah@cyberdyne-systems.com",
    "company": "Cyberdyne Systems",
    "budget": "$15,000",
    "message": "We need an urgent enterprise demo and timeline for migrating 500 seats."
  }'
```

Expected Response:
```json
{
  "status": "success",
  "qualificationTier": "HOT"
}
```

Check your Slack channel: you should see a red-bordered alert marked **🔥 HOT LEAD ALERT** with score ≥ 70.
