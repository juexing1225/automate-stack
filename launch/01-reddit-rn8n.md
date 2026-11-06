# Channel 1 — r/n8n

**Rules to respect:** r/n8n bans naked self-promo. Post the *solution* first, mention the paid
kit only if someone asks, or in a single line at the bottom. Accounts with no history get
auto-removed — if your account is new, comment in the sub for a week first.

---

## Title

I got tired of scoring leads by hand in n8n, so I wrote the scoring logic down

## Body

Sharing the actual scoring function, because most "lead scoring" templates I found were
just `if budget > X then hot`.

Mine scores 0–100 on three signals and runs before anything hits the CRM:

- **Corporate domain (+30)** — free-provider list (gmail/qq/163/outlook) gets 0
- **Budget stated (+25 / +15)** — `k`, `000`, `enterprise`, or a `$` followed by a digit
- **Message intent (+25 / +15)** — needs 2+ of: demo, pricing, hire, contract, urgent,
  timeline, decision, team, integrate, migration

Tiers: ≥70 HOT (red Slack), ≥45 WARM, else NURTURE.

The bit that actually matters: **score before the CRM write**, not after. If you score
after, your CRM is already full of junk and you are scoring junk.

```javascript
const lead = $input.item.json;
let score = 20;
const free = ['gmail.com','yahoo.com','hotmail.com','outlook.com','icloud.com','163.com','qq.com'];
const domain = lead.email.split('@')[1] || '';
if (!free.includes(domain)) score += 30;

const b = (lead.budget || '').toLowerCase();
if (/k|000|enterprise|\$[1-9]/.test(b)) score += 25;
else if (b) score += 15;

const msg = (lead.message || '').toLowerCase();
const hits = ['demo','pricing','hire','contract','urgent','timeline','decision','team','integrate','migration']
  .filter(k => msg.includes(k)).length;
if (hits >= 2 || msg.length > 180) score += 25;
else if (hits === 1 || msg.length > 50) score += 15;

return { json: { ...lead, score: Math.min(100, score), tier: score >= 70 ? 'HOT' : score >= 45 ? 'WARM' : 'NURTURE' } };
```

One gotcha worth knowing: `document.activeElement` is not the trigger. If you are routing
this off a webhook, the payload is under `body`, not at the root — half the "my webhook
returns undefined" threads are this.

(I packaged the full thing — intake + daily rollup + Slack payloads + a rollback doc — as a
$39 kit, link in my profile. The function above is the part worth stealing for free.)
