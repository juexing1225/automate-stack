# Rollback Guide: Lead Intake Automation Kit

If you ever need to decommission or revert this workflow, follow these steps to cleanly undo everything in under 5 minutes:

1. **Deactivate in n8n**:
   - In n8n, locate `Lead Intake Automation` and `Lead Intake Daily Digest`.
   - Toggle the **Active** switch to **OFF**.
   - Incoming webhooks will immediately stop receiving and processing requests.

2. **Revoke Webhook URL**:
   - Point your website/contact form endpoint back to your previous form handler or inbox.
   - Delete the incoming Slack webhook app if no other service is using it.

3. **Verify Clean Removal**:
   - Check the **Executions** tab in n8n to ensure no pending or stuck executions remain.
   - Delete the two workflow objects from your n8n workspace. No database tables or background daemons were provisioned.
