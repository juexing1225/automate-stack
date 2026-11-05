# Make (Integromat) Blueprint: Lead Intake Automation

If you use Make instead of n8n, replicate the pipeline with the following module chain:

1. **Custom Webhook** (`Webhook Intake`)
   - Method: POST
   - Data structure: `{ name: text, email: text, company: text, budget: text, message: text }`

2. **Tools > Set Variable** (`Validate & Domain`)
   - Sanitize email: `lower(trim(email))`
   - Extract domain: `split(email; "@")[2]`

3. **Router** (`Filter Hot vs Standard`)
   - Branch 1: Route if `contains(domain; ".") AND NOT contains(freeEmailList; domain)` AND `length(message) > 50` (Hot)
   - Branch 2: Otherwise (Standard)

4. **Slack > Create a Message** (`Send Alert`)
   - Use color `#ff334b` for Hot leads, `#2ea44f` for Standard leads.

5. **Google Sheets / CRM > Add a Row** (`Store Lead`)
   - Insert timestamp, name, email, company, score.

6. **Webhook Response**
   - Status: 200
   - Body: `{"status": "success"}`
