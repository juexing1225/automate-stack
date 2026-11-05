# Make (Integromat) Blueprint: Support Triage & SLA Guardian

To build this in Make:

1. **Custom Webhook**: Receive support ticket payload (`customerEmail`, `subject`, `message`, `plan`).
2. **OpenAI > Create a Completion**:
   - Classify urgency and sentiment into JSON format.
3. **Router**:
   - Route 1: Urgency is `CRITICAL` or sentiment is `ANGRY` -> Immediate Slack alert to `#support-red-alerts`.
   - Route 2: Otherwise -> Log ticket to Airtable / Zendesk with suggested draft.
4. **Webhook Response**: Return 200 OK with triage metadata.
