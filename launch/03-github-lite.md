# Channel 3 — GitHub free-lite funnel

GitHub is the only channel that compounds without an audience. Devs search
`n8n lead scoring workflow` on GitHub, not Google.

**Not done autonomously** because publishing a public repo should be under your own account
and name, not a bot identity. The content below is ready.

## Repo: `n8n-automation-kits`

Description: `Free, importable n8n workflow fragments. Paid kits include the full Setups and rollbacks.`

```
n8n-automation-kits/
├── lead-scoring/
│   └── score-lead.js          # the 0-100 function, MIT
├── invoice-ladder/
│   └── aging-ladder.js        # day 3 / 7 / 14 / 30 bucketing, MIT
├── content-repurpose/
│   └── prompts/               # thread / carousel / newsletter, MIT
├── README.md
└── LICENSE                    # MIT
```

## README skeleton

```markdown
# n8n Automation Kits — free fragments

Snippets I kept rewriting across projects. MIT, take them.

## Lead scoring (0-100)
Pure Code node, no API calls. Scores domain + budget + message intent.
👉 [score-lead.js](lead-scoring/score-lead.js)

## Invoice aging ladder
Buckets open Stripe invoices into the only four days worth emailing: 3, 7, 14, 30.
👉 [aging-ladder.js](invoice-ladder/aging-ladder.js)

## Content repurposing prompts
Three prompts that forbid invented metrics. 👉 [prompts/](content-repurpose/prompts/)

---

Full packaged kits (importable JSON, Setup docs, rollback guides, Make recipes):
[AutomateStack](https://juexing1225.github.io/automate-stack/)
```

## Why this works

- MIT licence makes it linkable from forum answers without looking like spam
- GitHub repo pages rank for `n8n <thing>` queries within weeks
- Every README ends on the paid link, which is the only place the pitch appears
