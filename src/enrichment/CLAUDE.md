# Email Enrichment Pipeline (Layer 0–3)

Finds verified email addresses for discovered contacts. Runs sequentially: Layer 0 
(domain resolution) → Layer 1 (site scraping) → Layer 2 (SMTP verification) → 
Layer 3 (Hunter.io fallback).

## Layer 0: Domain Resolution

Fails fast if the company has no `domain` (~half of discoveries). First attempts to 
resolve one by deriving from existing contact email, else web-searches the official 
site (rejecting social / job-board / directory hosts). Resolved domain persists back 
to `Company` (unique constraint prevents overwrites). Contacts with **no name** are 
skipped at persist time (can't be pattern-matched).

**Module**: `src/enrichment/domain_resolver.py`

## Layer 1: Site Scraping

Downloads up to 6 pages per domain (`/`, `/contacto`, `/contact`, `/nosotros`, 
`/equipo`, `/about`). Fetches `robots.txt` with 5s timeout (cached per domain); 
8s page timeout, no retry. HTTP fallback on root only.

Extracts emails (regex) + Argentine phone/WhatsApp. **Named-person matches** 
(first/last in local part) are taken immediately as `verified` / `site_scrape`. 
**Generic inboxes** (`info@`, `contacto@`, etc.) are captured as fallback; real 
published addresses beat pattern guesses.

**Module**: `src/enrichment/scraper.py`

## Layer 2: Pattern Generation + SMTP Verification

Generates 6 email permutations: `first.last@`, `flast@`, `first@`, `firstlast@`, 
`f.last@`, `last@`. If Layer 1 found domain emails, infers the corporate pattern 
and prioritizes it.

Verifies candidates via `EMAIL_VERIFIER_PROVIDER`:
- `neverbounce` (key: `NEVERBOUNCE_API_KEY`)
- `millionverifier` (default; key: `EMAIL_VERIFIER_API_KEY`)
- `local` — free MX/A/syntax pre-filter (never returns `valid`, only catches dead domains)
- `smart` / `chain` — runs `local` first, calls paid backend only if undecided (saves credits)

All map to: `valid` / `catch_all` / `invalid` / `unknown`. Stops on first `valid`; 
`catch_all` stored as `probable`.

⚠ **Verifier at 0 credits** → all candidates return `unknown` → emails degrade to 
`probable`/`pattern_unverified` → bounces. Keep funded.

**Modules**: `src/enrichment/patterns.py`, `src/enrichment/providers/*`

## Layer 3: Hunter.io Fallback

Calls Hunter.io email finder API (`HUNTER_API_KEY`). Score ≥ 90 → `verified`; 
≥ 50 → `probable`.

**Module**: `src/enrichment/providers/hunter.py`

## Email Precedence (Winner)

After all layers, the contact's email is chosen in this order:
1. **Verified named email** — Layer 1 name-match, Layer 2 SMTP `valid`, or Hunter ≥90
2. **Real published generic inbox** — `info@`/`contacto@` from site (`site_scrape_generic`, stored `verified`). Real, won't bounce. Beats guesses.
3. **Unverified/uncertain guess** — `pattern_unverified`, `catch_all`, or Hunter ≥50 (bounce-prone path, used only if no generic inbox exists)

This prevents pushing invented `first.last@` when real `info@` sits on the company's contact page.

## Enrichment Fields on `Contact` Model

| Field | Values |
|---|---|
| `email_status` | `verified`, `probable`, `not_found` (final); `bounced` (set by bounce check) |
| `email_source` | `site_scrape`, `site_scrape_generic`, `pattern_verified`, `pattern_unverified`, `hunter` |
| `phone_whatsapp` | nullable |
| `enriched_at` | datetime |
| `enrichment_log` | JSONB — per-layer attempt log + `attempts` (retry counter) + `bad_emails` (blocklist) |

## Bounced-Email Recovery

When an email bounces, recovery **blocklists** the bad address and re-runs enrichment 
to find alternatives. Pipeline reads `bad_emails` and skips them in all layers. 

⚠ Recovery still needs a **funded verifier** to confirm alternatives.

**Module**: `src/tools/recovery.py`

## Running Enrichment

- **Web UI**: "Enrich" per contact or "⚡ Enrich All" (async, sequential, 2s delay)
- **CLI**: `python run.py --enrich-run <run_id>`
- Both skip already-enriched contacts; 3-minute hard cap per contact
- Each contact: ~15–70s (scrape + SMTP + Hunter)
