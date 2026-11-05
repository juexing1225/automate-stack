# Setup Guide: Content Repurposer Kit

Transform one long post into platform-native assets with a built-in human review gate.

## Configuration Table

Replace the placeholders in the imported workflows with your own endpoints and keys:

| Placeholder | Where to get it | Example |
| :--- | :--- | :--- |
| `YOUR_OPENAI_OR_LLM_API_KEY` | OpenAI API Keys dashboard | `sk-proj-...` |
| `YOUR_REVIEW_GATE_WEBHOOK_URL` | Notion / Airtable / Google Sheets webhook endpoint | `https://api.notion.com/v1/pages` or `https://hook.make.com/xxxx` |
| `YOUR_SLACK_WEBHOOK_URL` | Slack App / Incoming Webhooks | `https://hooks.slack.com/services/T00/B00/XXXX` |

## Step-by-Step Installation

1. In your n8n workspace, click **Workflows** > **Import from File**.
2. Import `n8n/content-repurposer.json`.
3. In nodes **Generate X Thread**, **Generate LinkedIn Carousel**, and **Generate Newsletter**, update `YOUR_OPENAI_OR_LLM_API_KEY`.
4. In **Push to Review Gate**, replace `YOUR_REVIEW_GATE_WEBHOOK_URL` with your review board webhook.
5. In **Alert Slack Reviewer**, replace `YOUR_SLACK_WEBHOOK_URL`.
6. Import `n8n/content-batch.json` if you plan to queue multiple articles automatically.

## Copy-Paste Test Command

Send a sample article payload to test the generation and review gate:

```bash
curl -X POST "http://localhost:5678/webhook-test/repurpose-content" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Why Autonomous Systems Need Deterministic Review Gates",
    "author": "Operator",
    "content": "Language models excel at transformation, compression, and stylistic framing, but they cannot vouch for physical truth. When building autonomous content pipelines, auto-publishing raw generations is a failure mode. A deterministic human-in-the-loop review gate preserves editorial integrity while removing 90% of the manual rewriting toil."
  }'
```

Expected Response:
```json
{
  "status": "queued_for_review",
  "contentId": "art_..."
}
```

Check your Slack: you will receive an alert with the draft link awaiting your approval.
