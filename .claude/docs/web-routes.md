# Web Routes Reference

All routes are served by the Flask app in `src/web.py`.

## Runs & Reports

| Route | Method | Description |
|---|---|---|
| `/` | GET | All runs list (profile filter, hide failed) |
| `/run/<id>` | GET | Run detail — quick wins, strategic, contacts, outreach drafts (all sections collapsed by default) |
| `/run/latest` | GET | Redirect to latest run |
| `/run/<id>/delete` | POST | Delete a failed run and its report |
| `/run/<id>/export/<fmt>` | GET | Export as `csv` or `md` |
| `/run/<id>/professional-report` | GET | View the AI professional report |
| `/run/<id>/professional-report/generate` | POST | Generate the AI professional report (async, reasoning model) |
| `/run/<id>/professional-report/download` | GET | Download the professional report as Markdown |

## Enrichment

| Route | Method | Description |
|---|---|---|
| `/run/<id>/enrich-all` | POST | Bulk enrich all **un-enriched** contacts (async, sequential, 2s delay) |
| `/run/<id>/enrich-status` | GET | Enrichment progress `{done, total, failed, running, current_name}` |
| `/contact/<id>/enrich` | POST | Enrich a single contact |
| `/contact/<id>/set-email` | POST | Manually set a contact's email (sets status=verified, source=manual) |

## Zoho Mail Integration

| Route | Method | Description |
|---|---|---|
| `/run/<id>/zoho-drafts` | POST | Push outreach drafts to Zoho Mail |
| `/contact/<id>/zoho-draft` | POST | Push a single contact's draft to Zoho Mail |

## Bounces & Replies

| Route | Method | Description |
|---|---|---|
| `/bounces/scan` | GET | Preview Zoho bounces matched to contacts (read-only) |
| `/bounces/apply` | POST | Mark matched bounced contacts (`email_status="bounced"`) |
| `/contact/<id>/clear-replied` | POST | Clear replied_at + auto-set response_received, re-entering follow-up cadence |

## Contacts & Follow-ups

| Route | Method | Description |
|---|---|---|
| `/contacts-report` | GET | Contacted companies grouped by profile (dedup, follow-up tracking) |
| `/company/<id>/toggle-contact` | POST | Mark company as contacted |
| `/company/<id>/feedback` | GET/POST | Get/save contact feedback |
| `/follow-ups` | GET | Follow-up dashboard — pending/overdue, upcoming, drafted this week, replied |
| `/follow-ups/push-now` | POST | Bring-forward: draft + push a follow-up now, bypassing cadence (`company_id`) |

## Search & Browse

| Route | Method | Description |
|---|---|---|
| `/search` | GET | Browse/search companies (25/page pagination); contacts panel when `?q=` set |
| `/search/export/<fmt>` | GET | Export the company listing (respects `?q=` filter) as `csv` or `md` |

## Quick Run (Fast Email Hunting)

| Route | Method | Description |
|---|---|---|
| `/quick-run` | GET | Quick Run form + history list (last 15 runs) |
| `/quick-run` | POST | Start a Quick Run (creates DiscoveryRun, spawns background thread) |
| `/quick-run/<run_id>` | GET | Quick Run results page |
| `/quick-run/<run_id>/status` | GET | Polling endpoint `{phase, done, total, error}` |
| `/quick-run/<run_id>/push-all-zoho` | POST | Push all **eligible** drafts to Zoho (verified/probable, not already contacted/pushed) |
| `/quick-run/<run_id>/push-selected-zoho` | POST | Push only the selected contacts (eligibility-filtered) |
| `/quick-run/<run_id>/push-one-zoho` | POST | Push a single company's draft to Zoho Mail |

## Profiles & Schedule

| Route | Method | Description |
|---|---|---|
| `/profiles` | GET | Profile list |
| `/profiles/new` | GET/POST | Create profile |
| `/profiles/<id>/edit` | GET/POST | Edit profile |
| `/schedule/update` | POST | Update cron schedule + profile |
| `/toggle-scheduler` | POST | Pause/resume scheduler |

## Manual Trigger & Logging

| Route | Method | Description |
|---|---|---|
| `/trigger` | POST | Manual discovery run (requires TRIGGER_PASSWORD) |
| `/logs` | GET | SSE log stream (JSON) |

## Navigation (Header)

Inline search bar → `⚡ Quick Run` → `Runs` → `Contactados` → `Follow-ups` → `Perfiles` → `Logout`.
Visual separators between search/actions and the logout link.

## Key UI Features

### Run Detail
- All sections (Opportunities, Outreach, Follow-ups) **collapsed by default**
- Email status badges: ✅ verified / 🟡 probable / 🔵 LinkedIn only / 🔴 not found
- Per-contact "Enrich" button (inline result update)
- "⚡ Enrich All" bulk button with live progress counter (`N OK · M error`)
- "📧 Zoho Drafts" button (visible only if Zoho configured)
- Responsive: table → stacked cards on mobile

### Contacted Companies Report (`/contacts-report`)
- **De-duplicated**: rows for same business merge into one card
- Grouped by profile; each profile section is a collapsible `<details>` (collapsed by default)
- Follow-up highlighting: ⚠ overdue (red border), 📅 Hoy (amber), upcoming (accent)
- Card actions: **💬 Feedback** (modal) + **✏️ manual email button** + **✕ Desmarcar** (remove ContactStatus)
- Stats bar: total contacted, respondieron, rebotaron, follow-ups scheduled, overdue
- **Filter bar** (client-side pills): Todas / 📭 Rebotadas / ⏰ Seguimiento / ✅ Exitosas

### Quick Run Results
- Flat table: Empresa | Contacto | Email badge | Descripción | Draft | Zoho | Seguimiento
- Per-row checkbox (pre-checked for eligibles; ineligible greyed with reason)
- **"Push seleccionados (N)"** → push only selected
- **"Push todos los elegibles"** → push all eligible
- Per-row "📧" button (eligible only) → push single company
- Draft preview modal with copy-to-clipboard
- History list on form page

### Follow-ups (`/follow-ups`)
- Weekly summary: pending/overdue (cadence due), **upcoming** (eligible, not yet due, within `?within=N` days), drafted this week, replied
- "⏩ Hacer hoy" button (pending + Próximos table) to draft early
- "↩ Reactivar" button (Respondieron section) to clear false-positive reply + re-enter cadence
- Stats bar
