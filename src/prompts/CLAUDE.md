# Outreach & Follow-Up Email Generation

## Outreach Email (`build_outreach_prompt()`)

Used by:
- Workflow `generate_outreach` node (Haiku or `OUTREACH_MODEL`)
- Worker draft generator (same Haiku + instructor pattern)
- Quick Run results

Generates customer-facing email drafts. Uses **`OUTREACH_MODEL`** (default Sonnet 
`claude-sonnet-4-6`) for quality. Enforces hard **grounding rules** to prevent hallucination:

- Reference **ONLY** facts in the company payload
- Never claim the company "doesn't / lacks / hasn't" something (absence unverifiable)
- If data thin, open with truthful industry/role observation instead of inventing

**Profile customization**: Profile's `outreach_instructions` (pitch, value props, 
proof points, what to emphasize/avoid) is injected as `WHAT <AGENT> OFFERS` block — 
the main lever to improve message quality per product.

**Shape enforced**: greeting → researched hook → one value bridge → optional true 
proof → one low-friction CTA → short sign-off. "Earn the reply, don't pitch" approach. 
Expanded banned-phrase list.

**Language**: Per-profile via `outreach_language`:
- `es` (default) — Argentine voseo (informal, warm)
- `en` — warm professional English

Applied by `build_outreach_prompt()` in `src/prompts/outreach.py`. Both workflow node 
and worker draft generator call it → stay in sync.

**Module**: `src/prompts/outreach.py`

## Follow-Up Email (`build_followup_prompt()`)

Used by:
- Worker phase 4 (`run_followups()`)
- `/follow-ups` page ("Hacer hoy" button)
- Background enrichment after a run

Generates follow-up drafts for already-contacted leads without replies. Uses Haiku 
(much cheaper than Sonnet). Constraints:
- 50–120 words
- References the original outreach
- Single CTA
- Subject = `"Re: " + original_subject`

**Language**: Reuses profile's `outreach_language` setting (Argentine voseo default).

**Cadence**: Follows `FOLLOWUP_FIRST_DAYS=4` (initial touch + 4d), then 
`FOLLOWUP_SECOND_DAYS=10` (first follow-up + 6d). Max 2 follow-ups per company 
(`FOLLOWUP_MAX=2`).

**Threading caveat**: Standalone `"Re:"` draft (no `In-Reply-To` header). Cadence 
assumes first-touch draft sent same day pushed.

**Module**: `src/prompts/followup.py`

## Instructor Integration

Both prompts use `instructor` (structured output library) to ensure well-formatted, 
escaped JSON. Prevents prompt injection and malformed email bodies.
