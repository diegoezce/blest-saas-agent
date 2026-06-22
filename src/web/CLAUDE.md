# Flask Web UI & Routes

Flask app in `src/web.py`. All routes listed in `@.claude/docs/web-routes.md` 
(big reference table).

## Key Features

**Navigation** (header): Inline search → Quick Run → Runs → Contactados → 
Follow-ups → Perfiles → Logout. Visual separators.

**Global Search** (`/search`):
- No query: lists all companies (25/page pagination)
- With query: filters companies + shows matching contacts
- Per-card actions: Feedback modal + toggle-contact button
- CSV/MD export respecting active filter

**Run Detail** (`/run/<id>`):
- All sections (Opportunities, Outreach, Follow-ups) **collapsed by default**
- Email status badges: ✅ verified / 🟡 probable / 🔵 LinkedIn only / 🔴 not found
- Per-contact "Enrich" button (inline result) + "⚡ Enrich All" (live progress counter)
- "📧 Zoho Drafts" button (visible only if Zoho configured)
- Responsive: table → stacked cards on mobile

**Quick Run** (`/quick-run`):
- Fast email-hunting workflow: discover → auto-enrich → push to Zoho
- Discovery + enrichment run sequentially in background
- Results: flat table with per-row checkboxes, inline draft preview, Zoho push buttons
- Enrichment strategy: shows all discovered companies, enriches only contacts without email
- Eligibility-gated: only verified/probable emails, skips already-contacted/pushed
- Persists enriched contact IDs to DB (`DiscoveryRun.enriched_contact_ids` JSONB) for page reload recovery

**Contacted Companies Report** (`/contacts-report`):
- Cross-run view of all `ContactStatus` records (follow-up tracking)
- Grouped by profile (collapsible `<details>`, collapsed by default)
- **De-duplicated**: rows for same business merge into one card
- Card actions: Feedback modal + manual email button + Desmarcar (remove ContactStatus)
- Stats bar + client-side filter pills (Rebotadas, Seguimiento, Exitosas)
- **"🔍 Buscar emails faltantes"** button: finds all companies with opportunities but no
  contacts, creates placeholder contacts, runs enrichment (Layer 1 + Layer 4) on each

**Follow-ups** (`/follow-ups`):
- Weekly summary: pending/overdue, **upcoming** (eligible, not due), drafted this week, replied
- "⏩ Hacer hoy" button to draft + push immediately, bypassing cadence
- "↩ Reactivar" to clear replied detection (override false-positives)

**Routes for Enrichment/Zoho**:
- `POST /run/<id>/enrich-all` — bulk enrich (async, sequential, 2s delay); re-enriches contacts with no email
- `GET /run/<id>/enrich-status` — poll progress `{done, total, failed, running, current_name}`
- `POST /enrich-missing-contacts` — creates placeholder contacts for companies with no contacts, runs enrichment async
- `GET /enrich-missing-contacts/status` — poll progress for the above
- `POST /run/<id>/zoho-drafts` — push all outreach drafts to Zoho
- `POST /contact/<id>/set-email` — manually set email (sets status=verified, source=manual)

**Bounce & Reply Detection**:
- `GET /bounces/scan` — preview Zoho bounces matched to contacts (read-only)
- `POST /bounces/apply` — mark matched contacts bounced
- Follow-up detection auto-runs in worker (sets `Contact.replied_at`)

**Profiles** (`/profiles`, `/profiles/new`, `/profiles/<id>/edit`):
- CRUD for profiles
- Form fields: targeting, tone, language, outreach instructions, custom scoring rubric

## Key Implementation Notes

- **Async enrichment** — `POST /run/<id>/enrich-all` spawns background thread, 
  polls via JS at 2s interval. Saves enriched contact IDs to DB after completion for recovery
- **Scheduler** — starts paused by default on deploy; must be manually activated from web UI 
  to prevent accidental automatic runs
- **Session/login** — basic auth via `WEB_PASSWORD` env var (default: blest2024)
- **SSE logs** — `GET /logs` streams JSON log events (used by dashboard)
- **Jinja2 templates** — responsive, mobile-friendly; `data-label` attributes for 
  stacked cards

Full route reference: `@.claude/docs/web-routes.md`
