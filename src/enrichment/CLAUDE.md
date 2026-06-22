# Email Enrichment Pipeline (Layer 0–4)

Finds verified email addresses for discovered contacts. Runs sequentially: Layer 0 
(domain resolution) → Layer 1 (site scraping) → Layer 2 (SMTP verification) → 
Layer 3 (Hunter.io fallback) → Layer 4 (web search, conditional).

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

## Layer 4: Web Search (Tavily) — Conditional

Only runs if email still not `verified` after Layers 0–3. Replicates manual 
"empresa email" Google search. Runs for **both named and nameless contacts**.

Queries built in order of specificity:
1. Named contact + company (`"{first} {last}" "{company}" email`) — only if named
2. Company + role/context (`"{company}" {role} email`) — only if role known
3. Generic company terms (`"{company}" email`, `"{company}" employees email`, team, staff)
4. Spanish variants (`"{company}" contacto email`, `"{company}" empleados email`)

Extracts emails from Tavily snippet results, filters by domain/reputation. Includes 
0.2s delay between queries to avoid rate-limiting.

**Domain matching**: For named contacts, requires exact domain match (or subdomain).
For **nameless placeholders**, accepts alternate TLDs sharing the same brand root
(e.g. `southerncode.us` when stored domain is `southerncode.com`) — companies often
use a different TLD than what discovery initially captured.

**Ranking logic:**
1. Named match (first/last in local part) → `web_search` (high confidence)
2. Generic inbox only (`info@`, `contacto@`) → `web_search_generic` (medium)
3. No useful result → email unchanged (no regression)

**v1 design:** No SMTP confirmation of web-found emails (precision-over-cost tradeoff). 
If post-production metrics show high bounce rates on `web_search` source, v1.1 can add 
SMTP validation.

**Module**: `src/enrichment/web_email_finder.py`

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
| `email_source` | `site_scrape`, `site_scrape_generic`, `pattern_verified`, `pattern_unverified`, `hunter`, `web_search`, `web_search_generic` |
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
- **Web UI**: "🔍 Buscar emails faltantes" in `/contacts-report` — bulk-enrich all companies with no contacts
- **CLI**: `python run.py --enrich-run <run_id>`
- All skip already-enriched contacts; 3-minute hard cap per contact
- Each contact: ~15–90s (scrape + SMTP + Hunter + web search if needed)
  - Layer 4 (web search) only runs if email not yet verified; adds ~10–20s when triggered
