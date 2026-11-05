# Setup Guide: Support Triage & SLA Guardian Kit

Instantly classify incoming customer issues, prevent VIP churn, and safeguard response SLAs.

## Configuration Table

Replace the placeholders in the imported workflows:

| Placeholder | Where to get it | Example |
| :--- | :--- | :--- |
| `YOUR_OPENAI_OR_LLM_API_KEY` | OpenAI API Keys Console | `sk-proj-...` |
| `YOUR_SLACK_WEBHOOK_URL` | Slack App / Incoming Webhooks | `https://hooks.slack.com/services/T00/B00/XXXX` |
| `YOUR_HELPDESK_OR_CRM_WEBHOOK_URL` | Zendesk / Crisp / Airtable Webhook | `https://api.airtable.com/v0/...` |

## Installation Steps

1. In n8n, click **Workflows** > **Import from File**.
2. Import `n8n/support-triage.json`.
3. In **Analyze Sentiment & Triage**, update `YOUR_OPENAI_OR_LLM_API_KEY`.
4. In **Send Slack Escalation**, update `YOUR_SLACK_WEBHOOK_URL`.
5. In **Sync Ticket to CRM**, replace `YOUR_HELPDESK_OR_CRM_WEBHOOK_URL`.
6. Import `n8n/support-sla-monitor.json` and update both placeholders.
