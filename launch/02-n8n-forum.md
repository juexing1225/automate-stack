# Channel 2 — n8n Community Forum (community.n8n.io)

Highest-intent audience that exists for this product. Post in **Share your workflow**, not
**Jobs**. Forum regulars will click a profile link; they will report a naked ad.

---

## Title

Lead scoring before the CRM write — the 0-100 function I keep rebuilding

## Category

Share your workflow

## Body

Every lead-scoring template I have seen scores on one field. Here is the version I ended up
with after three client projects, posted because I keep pasting it into DMs.

**Ordering is the whole design.** Score runs on the normalized webhook payload, before any
CRM or Sheets node. Scoring after the write means you are ranking records you already
polluted.

Signals, all local, no API calls, no LLM:

| Signal | Weight | Rule |
| --- | --- | --- |
| Corporate domain | +30 | not in the free-provider list |
| Budget stated | +25 / +15 | `k`, `000`, `enterprise`, or `$` + digit |
| Message intent | +25 / +15 | 2+ of demo/pricing/hire/contract/urgent/timeline/decision/team/integrate/migration |

```javascript
let score = 20;
const free = ['gmail.com','yahoo.com','hotmail.com','outlook.com','icloud.com','163.com','qq.com'];
const domain = lead.email.split('@')[1] || '';
if (!free.includes(domain)) score += 30;
// ... see the Code node in the shared workflow for the rest
```

Two things I got wrong first time, so you do not have to:

1. **`$json.body` vs `$json`** — webhook payloads nest the body; referencing the root gives
   you undefined and a silent 0 score.
2. **Don't `throw` on a missing email in the same Code node as the scoring.** The error kills
   the execution and you lose the alert. Validate in its own node, respond 200, then branch.

I also put a daily 09:00 rollup in the same workflow set so you get one message a day instead
of forty.

Full bundle (intake, rollup, Slack colour by tier, Make recipe, rollback doc) is on Gumroad
for $39 if you want the packaged version: https://juexing.gumroad.com/l/lead-intake — the
scoring function above is the free part, take it either way.
