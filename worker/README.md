# Blest Worker

Background worker that runs on a local **Windows mini PC** on a schedule and operates on the
**existing** rows in the Railway PostgreSQL database. It does **not** discover companies — that's
the job of the main app (`run.py` / Railway). Think of it as the "hands":

- **`run.py` / Railway** = the brain → discovers companies, scores them, finds contacts, writes drafts.
- **`worker/worker.py`** = the hands → finds the contacts' emails and pushes outreach drafts to Zoho Mail.

Railway stays the single source of truth; the worker only reads from and writes to that shared DB.
No data is stored locally (only logs).

---

## What it does (per run)

1. **Enrichment** — takes up to `WORKER_ENRICH_BATCH` contacts that have no email yet
   (`enriched_at IS NULL`) and runs the enrichment pipeline:
   **Layer 0** resolve a missing company domain → **Layer 1** scrape the site →
   **Layer 2** generate email patterns + verify via MillionVerifier → **Layer 3** Hunter.io fallback.
   When `WORKER_RETRY_FAILED=true` and the batch isn't full, it also **retries** previously failed
   *named* contacts (still no email) up to `WORKER_MAX_ATTEMPTS` passes — so contacts that failed
   only because the company had no domain succeed once Layer 0 resolves one.

2. **Zoho push** — for each company with a verified/probable contact email, pushes the best
   (highest-score) opportunity's draft to the Zoho Mail drafts folder. A **company-level guard**
   skips any company already contacted or pushed in a prior run, so the same company never gets
   duplicate outreach. If the opportunity has no draft yet, one is generated on the fly with Claude
   Haiku (in the profile's `outreach_language`). `zoho_pushed_at` is set after a successful push.

3. **Bounce check** — scans the Zoho inbox for bounce notifications (mailer-daemon/postmaster,
   "Undelivered"/"Undeliverable"; "delay" notices ignored), matches the failed addresses to
   contacts, and marks them `email_status="bounced"` (which also drops them from push
   eligibility). Toggle with `WORKER_CHECK_BOUNCES` (default on); non-fatal if the token lacks
   the READ scope. Same logic as the `📭 Chequear rebotes` button and `python run.py --check-bounces`.

4. **Follow-ups** — detects replies in the Zoho inbox (sets `Contact.replied_at`, skipping
   leads who already answered) and generates + pushes follow-up drafts for contacted leads with
   no reply, on a 2-touch cadence (~day 4 and ~day 10, max 2). Drafts are Spanish by default
   (profile `outreach_language`), 50–120 words, reference the original and have a single CTA.
   Toggle with `WORKER_FOLLOWUP` (default on); non-fatal if the token lacks the READ scope. Same
   logic as the `/follow-ups` page and `python run.py --detect-replies` / `--follow-ups`.

---

## Prerequisites

- **Python 3.11** installed, with the `py` launcher (`py -3.11` must work).
- This repo cloned to the machine (examples below assume `C:\Projects\BlestLeadsAgent`).
- A Zoho **Self-Client** app (for Zoho Mail OAuth).
- A `worker/.env` file (see Configuration).

---

## Setup

```powershell
# 1. From the project root, install dependencies
py -3.11 -m pip install -r requirements.txt

# 2. Create the worker config and fill in the values
copy worker\.env.example worker\.env
notepad worker\.env

# 3. Authorize Zoho Mail (one time).
#    Create a Self-Client at https://api-console.zoho.com
#    scope: ZohoMail.messages.READ,ZohoMail.folders.READ,ZohoMail.messages.CREATE,ZohoMail.accounts.READ
#    (READ scopes also enable bounce detection in the web UI; 10-min grant token)
py -3.11 run.py --zoho-auth <grant_token>
#    → stores .zoho_tokens.json in the project root

# 4. Test it once, manually
py -3.11 worker\worker.py
```

If step 4 prints "Worker finished." you're ready to schedule it.

---

## Configuration (`worker/.env`)

`worker/.env` is **gitignored** — never commit the real one. Copy from `worker/.env.example`.

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | Railway public PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | ✅ | Claude API key (Haiku for drafts) |
| `ZOHO_CLIENT_ID` | ✅ | OAuth2 client ID (self-client app) |
| `ZOHO_CLIENT_SECRET` | ✅ | OAuth2 client secret |
| `EMAIL_VERIFIER_PROVIDER` | — | Layer 2 verifier: `millionverifier` (default) or `neverbounce` |
| `EMAIL_VERIFIER_API_KEY` | — | MillionVerifier key (~$0.003/check). **Needs credits** — at 0 credits every candidate comes back `unknown` and emails are stored as unverified guesses (`probable`/`pattern_unverified`) |
| `NEVERBOUNCE_API_KEY` | — | NeverBounce key (used when `EMAIL_VERIFIER_PROVIDER=neverbounce`; 1,000 free/month) |
| `HUNTER_API_KEY` | — | Hunter.io key (25 free/month) |
| `FAST_MODEL` | — | Model override (default `claude-haiku-4-5-20251001`) |
| `WORKER_ENRICH_BATCH` | — | Contacts to enrich per run (default 15) |
| `WORKER_PUSH_BATCH` | — | Drafts to push per run (default 15) |
| `WORKER_ENRICH_DELAY` | — | Seconds between contacts during enrichment (default 3) |
| `WORKER_PUSH_DELAY` | — | Seconds between Zoho calls (default 1) |
| `WORKER_RETRY_FAILED` | — | Retry previously-failed named contacts (default `true`) |
| `WORKER_MAX_ATTEMPTS` | — | Max enrichment passes per contact incl. first (default 3) |
| `WORKER_CHECK_BOUNCES` | — | Phase 3: scan Zoho inbox + mark bounced contacts (default true; needs READ scope) |
| `WORKER_FOLLOWUP` | — | Phase 4: detect replies + push follow-up drafts (default true; needs READ scope) |
| `WORKER_FOLLOWUP_BATCH` | — | Follow-up drafts to push per run (default 15) |
| `WORKER_FOLLOWUP_DELAY` | — | Seconds between Zoho API calls in the follow-up phase (default 1) |

> The enrichment providers read API keys from `os.environ`, which is why the worker calls
> `load_dotenv(worker/.env)` at startup. If you run enrichment outside the worker, the keys must
> be exported or MillionVerifier/Hunter are silently skipped.

---

## Scheduling (run every day)

The worker is scheduled with **Windows Task Scheduler**, pointing at `worker/run_worker.bat`.
That launcher `cd`s to the project root and runs the worker via `py -3.11`, appending output to
`worker/worker_task.log`.

### Option 1 — one command (recommended)

Open **PowerShell or CMD as Administrator** and run:

```bat
schtasks /Create /TN "BlestWorker" /TR "C:\Projects\BlestLeadsAgent\worker\run_worker.bat" /SC DAILY /MO 1 /ST 09:00 /F
```

- `/SC DAILY /MO 1` → every day · `/ST 09:00` → at 09:00 (change as needed) · `/F` → overwrite if the task already exists.
- Runs **only while you're logged in**. To run even when no one is logged on, append your user + password:
  `... /RU diego /RP *` (it prompts for the password).

### Option 2 — GUI

Task Scheduler → **Create Basic Task** → name `BlestWorker` → **Daily** → pick a time →
**Start a program** → Program/script: `C:\Projects\BlestLeadsAgent\worker\run_worker.bat` → Finish.

### Switching an existing "every 2 days" task to daily

Either re-run the Option 1 command (the `/F` overwrites it), or in the GUI:
task → **Properties** → **Triggers** → **Edit** → set **Daily**, **Recur every: 1 days**.

### Useful commands

```bat
schtasks /Run    /TN "BlestWorker"      :: run now (test the scheduled task)
schtasks /Query  /TN "BlestWorker" /V   :: status / last run result
schtasks /Delete /TN "BlestWorker" /F   :: remove the task
```

> Task Scheduler will not start a second instance while one is still running (the default
> multiple-instance policy), so daily runs won't overlap even if a run takes several minutes.

---

## Running manually

```powershell
py -3.11 worker\worker.py        # direct
# or
worker\run_worker.bat            # same thing the scheduler runs (also writes worker_task.log)
```

---

## Logs

| File | What |
|---|---|
| `worker/worker.log` | The worker's own structured log (per-contact enrichment, pushes) |
| `worker/worker_task.log` | Raw stdout/stderr captured by `run_worker.bat` (catches startup crashes too) |

Both are gitignored.

---

## Operational notes

- **Throughput**: each run handles `WORKER_ENRICH_BATCH` (15) + `WORKER_PUSH_BATCH` (15). Running
  daily instead of every 2 days doubles the rate. If you have a backlog, raise those numbers in
  `worker/.env`.
- **Migrations**: `init_db()` runs at startup, so the worker applies any pending DB schema
  migrations automatically when it first connects.
- **No duplicate outreach**: the Zoho-push guard means a company contacted/pushed in any earlier
  run is never pushed again (see CLAUDE.md → "Cross-run dedup").
- **MillionVerifier credits**: with 0 credits, emails can't be SMTP-verified and are stored as
  `probable`/unverified guesses. Top up if you need verified-quality emails.
- **Switching the verifier (MillionVerifier ↔ NeverBounce)**: set `EMAIL_VERIFIER_PROVIDER=neverbounce`
  and `NEVERBOUNCE_API_KEY=...` in `worker/.env` (and in Railway env vars for the web/Quick-Run path).
  No code change or redeploy logic needed — the provider is picked at runtime by
  `get_verifier()`. Set it back to `millionverifier` to revert. NeverBounce gives 1,000 free
  checks/month, so it's a cheaper starting point than MillionVerifier's paid credits.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Zoho Mail not configured` then exits | Run `py -3.11 run.py --zoho-auth <grant_token>` (token expired or `.zoho_tokens.json` missing) |
| `ModuleNotFoundError` | Deps not installed in the 3.11 interpreter → `py -3.11 -m pip install -r requirements.txt` |
| `Enrichment: nothing to do` | All contacts already enriched — expected once the backlog is cleared (new contacts come from discovery runs) |
| Scheduled task "completes" but nothing happens | Open `worker/worker_task.log` for the real error; confirm `run_worker.bat` path in the task is correct |
| Emails all come back `probable` / never `verified` | MillionVerifier is out of credits (see above) |
| Task runs but can't find Python | `run_worker.bat` uses `py -3.11`; make sure the Python launcher + 3.11 are installed |
