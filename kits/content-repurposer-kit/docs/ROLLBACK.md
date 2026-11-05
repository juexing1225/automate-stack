# Rollback Guide: Content Repurposer Kit

To pause or retire the content repurposing engine:

1. **Deactivate in n8n**:
   - Turn off `Content Repurposer` and `Content Batch Queue Drain`.
   - Incoming webhooks will cease processing requests immediately.

2. **Revoke API Key**:
   - In your OpenAI Dashboard, revoke the dedicated API key used for repurposing.

3. **Verify Removal**:
   - Delete the workflows from n8n. No raw articles or output files remain on the n8n host.
