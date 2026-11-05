# Make (Integromat) Blueprint: SaaS Churn Preventer

1. **Schedule**: Every Monday 09:00 AM.
2. **HTTP / Mixpanel**: Query accounts with >60% drop in event count.
3. **Filter**: If `last14Days < prev14Days * 0.4`.
4. **Slack**: Post warning to `#churn-alerts`.
5. **Email / Resend**: Send personal concierge check-in email.
