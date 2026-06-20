# Company Dedup, Bounces, Follow-ups

## Company Deduplication

`_upsert_company()` in `src/tools/db_tools.py` ensures one `Company` row per real 
business (feedback never splits across duplicates):

1. Match by normalized **domain** (`_normalize_domain`)
2. Else exact name (`ILIKE`)
3. Else **normalized name** — lowercases, strips punctuation + legal suffixes 
   (SA, SRL, Inc, Ltd…) → "Acme S.A." == "Acme"

Cross-run dedup guards:
- **Discovery**: `run_discovery_node` dedups within a run, then drops any company 
  already in DB (matched by normalized name or domain). Controlled by 
  `exclude_known_companies` / `rediscover_after_days`.
- **Worker Zoho push**: Skips companies already contacted (`ContactStatus`) or 
  pushed in prior run → outreach never duplicated across runs.

**Display-time dedup**: `/contacts-report` also de-dups at render time; rows sharing 
a domain or normalized name merge into one card (contacts pooled), with the 
richest-feedback record canonical.

**Module**: `src/tools/db_tools.py`

## Contact Deduplication

Within a company at insert time in `persist_run_node`:
1. Match by **LinkedIn URL** (most reliable)
2. Else by **name** within the same `company_id`

On match, missing fields (`role`, `linkedin_url`, `email`) are backfilled from new run; 
no duplicate row created. Same person found across multiple runs = one row.

## Bounced-Email Recovery

When an email bounces, recovery **blocklists** the bad address (stored in 
`enrichment_log["bad_emails"]`), clears the email, and re-runs `enrich_contact`.

Pipeline reads `bad_emails` and skips them in Layer 1 (scrape match), Layer 2 
(pattern candidates), and Layer 3 (Hunter).

**Shared functions**: `select_bounced_contacts`, `recover_contact`, `run_recovery`

**CLI**: `python run.py --recover-bounced [N]` (default 50)

**Worker phase 1b**: `WORKER_RECOVER_BOUNCED` (default on), runs before enrichment 
so recovered emails get pushed the same run.

⚠ Needs **funded verifier** to confirm alternatives; at 0 credits, recovery only 
produces another unverified guess.

**Module**: `src/tools/recovery.py`

## Follow-Up Agent

Follows up with already-contacted leads that haven't replied. Shared logic; runs 
as worker **phase 4**, exposed via `/follow-ups` and CLI (`--detect-replies`, 
`--follow-ups`).

**Cadence** — `FOLLOWUP_FIRST_DAYS=4`, `FOLLOWUP_SECOND_DAYS=10`, `FOLLOWUP_MAX=2`:
- Eligibility: pushed opportunities with verified/probable email, no reply, no manual feedback
- Timing: `_followup_due_date(opp)` computes next touch (count==0 → push + 4d; count==1 → last_followup + 6d)
- Worker selection: `select_followup_candidates()` = eligible + due ≤ now
- UI: `select_upcoming_followups(within_days=7)` = eligible + not yet due (drives "Próximos")

**Drafting**: `generate_followup()` builds payload + calls Haiku with `build_followup_prompt()` 
(Spanish voseo by default via `outreach_language`; 50–120 words). Subject = `"Re: " + original`. 
`run_followups()` pushes each draft + bumps `followup_count` / `last_followup_at`.

**Bring-forward ("Hacer hoy")**: `push_followup_now(session, company_id)` generates 
+ pushes immediately, bypassing cadence wait (company must still be eligible). 
Exposed via `POST /follow-ups/push-now`.

**UI**: `/follow-ups` shows pending/overdue (cadence due), **upcoming** (eligible 
but not yet due, within N days), drafted this week, replied. Pending + Próximos 
each have **"⏩ Hacer hoy"** button. "↩ Reactivar" clears `replied_at` in Respondieron 
section (override false-positives).

**Threading caveat (v1)**: Follow-up is standalone `"Re:"` draft (no `In-Reply-To` 
header). Cadence clock assumes first-touch draft sent same day it's pushed.

**Module**: `src/tools/followups.py`
