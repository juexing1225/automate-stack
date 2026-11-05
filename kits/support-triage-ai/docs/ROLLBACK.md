# Rollback Guide: Support Triage & SLA Guardian Kit

To deactivate automated support triage:

1. **Turn off workflows**: In n8n, toggle `Support Triage & SLA Guardian` and `Support SLA Breach Monitor` to **OFF**.
2. **Revert webhook source**: Point your support contact form directly to your legacy inbox or ticket system.
3. **Revoke API keys**: Revoke the OpenAI key if dedicated to this workflow.
