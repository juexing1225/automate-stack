# Make (Integromat) Blueprint: Invoice Chaser Kit

To build this in Make:

1. **Schedule**: Run every weekday at 08:30 AM.
2. **Stripe > List Invoices**:
   - Status: `open`
   - Limit: 100
3. **Tools > Filter**:
   - Condition: `parseDate(now) - parseDate(due_date)` equals 3, 7, 14, or 30 days.
4. **Router**:
   - Path 1 (Day 3): Gentle email reminder.
   - Path 2 (Day 7): Polite follow-up email.
   - Path 3 (Day 14): Firm overdue notice.
   - Path 4 (Day 30): Slack alert to business owner (manual escalation).
5. **Email / Resend / SendGrid**:
   - Send email with Stripe invoice payment link.
6. **Slack > Create a Message**:
   - Notify `#billing-notifications`.
