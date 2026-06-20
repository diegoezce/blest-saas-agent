# CLI Commands Reference

## Discovery & Reporting

```bash
python run.py                        # Run discovery once (default profile)
python run.py --profile <ID>         # Run discovery for a specific profile
python run.py --report               # Show last run's dashboard
python run.py --report --date DATE   # Show report for DATE (YYYY-MM-DD)
```

## Web & Scheduler

```bash
python run.py --web                  # Start Flask web UI + embedded daily scheduler
python run.py --schedule             # Start scheduler daemon only
```

## Database

```bash
python run.py --setup                # Initialize/migrate database tables
```

## Contact Enrichment

```bash
python run.py --enrich-run <ID>      # Enrich all contacts for a run (Layer 0-4)
python run.py --recover-bounced [N]  # Retry bounced contacts (blocklist + re-enrich); N max (default 50)
```

## Zoho Mail Integration

```bash
python run.py --zoho-auth <TOKEN>    # Store Zoho Mail OAuth credentials (one-time setup)
python run.py --check-bounces        # Scan Zoho inbox for bounces, mark matched contacts
python run.py --detect-replies       # Scan Zoho inbox for replies, mark answered contacts
```

## Follow-ups

```bash
python run.py --follow-ups           # Generate + push follow-up drafts for unanswered leads
```

## Examples

```bash
# Discover + enrich for the default profile, then generate follow-ups
python run.py
python run.py --enrich-run <run_id>
python run.py --follow-ups

# Start the web UI (handles discovery scheduling automatically)
python run.py --web

# Manually trigger discovery for a specific profile, then report
python run.py --profile 2
python run.py --report

# Check for bounces and mark them
python run.py --check-bounces
```
