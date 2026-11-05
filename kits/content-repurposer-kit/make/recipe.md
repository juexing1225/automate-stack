# Make (Integromat) Blueprint: Content Repurposer Kit

To build this pipeline in Make:

1. **Custom Webhook**: Receive `title`, `content`, and `author`.
2. **Router (3 parallel branches)**:
   - Branch 1: **OpenAI > Create a Completion** using `prompts/thread.md`.
   - Branch 2: **OpenAI > Create a Completion** using `prompts/carousel.md`.
   - Branch 3: **OpenAI > Create a Completion** using `prompts/newsletter.md`.
3. **Array Aggregator**: Collect outputs from all 3 branches.
4. **Notion / Airtable > Create a Record**:
   - Set status to `Needs Human Review`.
   - Populate output fields with generated markdown.
5. **Slack > Create a Message**:
   - Post to `#content-review` with the direct record link.
