# Rollback Guide: Invoice Chaser Kit

To immediately stop all automated payment reminders:

1. **Deactivate in n8n**:
   - In n8n, locate `Invoice Chaser` and `Invoice Monthly Overdue Report`.
   - Flip both switches to **OFF**.
   - No further emails will be queued or sent to customers.

2. **Revoke Stripe Restricted Key**:
   - Go to Stripe Dashboard > Developers > API Keys.
   - Delete or revoke `AutomateStack Invoice Chaser`.
   - This physically terminates read access to your billing data.

3. **Verify Removal**:
   - Delete the workflow files from n8n. No customer data or payment information is stored locally.
