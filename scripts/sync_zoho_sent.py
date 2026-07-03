"""
One-time sync: backfill zoho_pushed_at on opportunities for companies that were
contacted by email but are missing the flag in the DB.

Two modes:
  - Default (--from-db): uses contact_status.contacted_at as timestamp source.
    Requires no extra Zoho scope. Covers all historical gaps.
  - --from-zoho: reads the Zoho Sent folder and matches by recipient address.
    Requires ZohoMail.messages.READ + ZohoMail.folders.READ scopes.
    More precise (uses real send timestamps and catches edge cases).

Usage:
    python scripts/sync_zoho_sent.py [--dry-run] [--from-zoho] [--limit N]

Options:
    --dry-run    Preview changes without writing to DB
    --from-zoho  Read Sent folder from Zoho (requires READ scope)
    --limit N    Max Zoho messages to scan (default: 500, --from-zoho only)
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Mode 1: DB-only backfill ─────────────────────────────────────────────────

def run_sync_from_db(dry_run: bool) -> None:
    """Backfill zoho_pushed_at using contact_status.contacted_at as timestamp.
    Covers every company marked contacted via email in any run.
    """
    from src.database.session import get_session
    from src.database.models import Contact, Opportunity, ContactStatus

    print(f"{'[DRY RUN] ' if dry_run else ''}Syncing from DB (contact_status)...")

    updated = 0
    already_ok = 0
    no_opp = 0

    with get_session() as db:
        # All companies contacted by email with at least one opportunity
        rows = (
            db.query(ContactStatus, Opportunity)
            .join(Opportunity, Opportunity.company_id == ContactStatus.company_id)
            .filter(ContactStatus.contact_method == "email")
            .filter(Opportunity.zoho_pushed_at.is_(None))
            .order_by(Opportunity.score.desc(), Opportunity.id.desc())
            .all()
        )

        # One best opp per company (query may return multiple opps per company)
        seen: set[int] = set()
        to_update: list[tuple[Opportunity, datetime]] = []
        for cs, opp in rows:
            if opp.company_id in seen:
                continue
            seen.add(opp.company_id)
            ts = cs.contacted_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            to_update.append((opp, ts))

        # Also check companies where draft_sent_at exists but opp missing pushed_at
        contact_rows = (
            db.query(Contact, Opportunity)
            .join(Opportunity, Opportunity.company_id == Contact.company_id)
            .filter(Contact.draft_sent_at.isnot(None))
            .filter(Opportunity.zoho_pushed_at.is_(None))
            .filter(~Contact.company_id.in_(seen))
            .order_by(Contact.draft_sent_at.asc())
            .all()
        )
        for c, opp in contact_rows:
            if opp.company_id in seen:
                continue
            seen.add(opp.company_id)
            ts = c.draft_sent_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            to_update.append((opp, ts))

        print(f"  Opportunities to backfill: {len(to_update)}")

        for opp, ts in to_update:
            print(f"  {'[DRY RUN] ' if dry_run else ''}BACKFILL  company_id={opp.company_id}  opp=#{opp.id}  score={opp.score}  ts={ts.strftime('%Y-%m-%d %H:%M')}")
            if not dry_run:
                opp.zoho_pushed_at = ts
                updated += 1
            else:
                updated += 1

        if not dry_run:
            db.commit()

    print()
    print("── Result ──────────────────────────────────")
    print(f"  {'Would update' if dry_run else 'Updated'} zoho_pushed_at : {updated}")
    if dry_run:
        print()
        print("Run without --dry-run to apply.")


# ── Mode 2: Zoho Sent folder sync ────────────────────────────────────────────

def fetch_sent_messages(limit: int) -> list[dict]:
    """Return list of {to_address, sent_at_ms, subject} from Zoho Sent folder.
    Requires ZohoMail.messages.READ + ZohoMail.folders.READ scopes.
    """
    import requests
    from src.integrations.zoho_mail import _get_access_token, _load_tokens

    _ACCOUNTS_URL = "https://mail.zoho.com/api/accounts"

    access = _get_access_token()
    tokens = _load_tokens()
    account_id = tokens.get("account_id")
    if not account_id:
        raise RuntimeError("No account_id stored. Re-run: python run.py --zoho-auth <token>")

    base = f"{_ACCOUNTS_URL}/{account_id}"
    headers = {"Authorization": f"Zoho-oauthtoken {access}"}

    fr = requests.get(f"{base}/folders", headers=headers, timeout=15)
    if fr.status_code == 401:
        print()
        print("ERROR: 401 Unauthorized on Zoho folders API.")
        print("Your current OAuth token lacks 'ZohoMail.messages.READ' and/or 'ZohoMail.folders.READ' scope.")
        print()
        print("To fix, regenerate the token with the following scope:")
        print("  ZohoMail.messages.CREATE,ZohoMail.accounts.READ,ZohoMail.messages.READ,ZohoMail.folders.READ")
        print()
        print("Then run:  python run.py --zoho-auth <new_grant_token>")
        print()
        print("Alternatively, run without --from-zoho to use the DB-only backfill (no extra scope needed).")
        sys.exit(1)
    fr.raise_for_status()

    folders = fr.json().get("data", [])
    sent = next(
        (f for f in folders if (f.get("folderName") or "").lower() in ("sent", "enviados", "sent items")),
        None,
    )
    if not sent:
        sent = next((f for f in folders if f.get("folderType") == "sent"), None)
    if not sent:
        print(f"Available folders: {[f.get('folderName') for f in folders]}")
        raise RuntimeError("Could not find Sent folder. Check folder names above.")

    folder_id = sent["folderId"]
    print(f"Found Sent folder: '{sent.get('folderName')}' (id={folder_id})")

    messages = []
    start = 1
    page = 50

    while len(messages) < limit:
        batch_limit = min(page, limit - len(messages))
        mr = requests.get(
            f"{base}/messages/view",
            headers=headers,
            params={"folderId": folder_id, "limit": batch_limit, "start": start},
            timeout=20,
        )
        if mr.status_code != 200:
            print(f"  Stopped at start={start}: HTTP {mr.status_code}")
            break
        batch = mr.json().get("data", [])
        if not batch:
            break

        for m in batch:
            to_addr = (m.get("toAddress") or "").lower().strip()
            if "<" in to_addr and ">" in to_addr:
                to_addr = to_addr.split("<")[-1].rstrip(">").strip()
            sent_at_ms = int(m.get("sentDateInGMT") or m.get("receivedDateInGMT") or 0)
            messages.append({
                "to_address": to_addr,
                "sent_at_ms": sent_at_ms,
                "subject": m.get("subject", ""),
            })

        start += len(batch)
        if len(batch) < page:
            break

    return messages


def run_sync_from_zoho(dry_run: bool, limit: int) -> None:
    """Backfill zoho_pushed_at by matching Zoho Sent emails to contacts in DB."""
    from src.database.session import get_session
    from src.database.models import Contact, Opportunity

    print(f"{'[DRY RUN] ' if dry_run else ''}Fetching up to {limit} sent messages from Zoho...")
    messages = fetch_sent_messages(limit)
    print(f"Fetched {len(messages)} sent messages.")

    if not messages:
        print("Nothing to sync.")
        return

    # Earliest sent_at per recipient address
    sent_by_email: dict[str, int] = {}
    for m in messages:
        addr = m["to_address"]
        if not addr or "@" not in addr:
            continue
        ts = m["sent_at_ms"]
        if addr not in sent_by_email or ts < sent_by_email[addr]:
            sent_by_email[addr] = ts

    print(f"Unique recipient addresses in Sent: {len(sent_by_email)}")

    updated = 0
    already_ok = 0
    no_contact = 0
    no_opp = 0

    with get_session() as db:
        contacts = db.query(Contact).filter(Contact.email.isnot(None)).all()
        contact_by_email: dict[str, Contact] = {
            (c.email or "").lower().strip(): c
            for c in contacts
            if (c.email or "").strip()
        }

        for addr, sent_ms in sent_by_email.items():
            contact = contact_by_email.get(addr)
            if not contact:
                no_contact += 1
                continue

            opp = (
                db.query(Opportunity)
                .filter_by(company_id=contact.company_id)
                .order_by(Opportunity.score.desc(), Opportunity.id.desc())
                .first()
            )
            if not opp:
                no_opp += 1
                continue

            if opp.zoho_pushed_at is not None:
                already_ok += 1
                continue

            sent_dt = datetime.fromtimestamp(sent_ms / 1000, tz=timezone.utc)
            print(f"  {'[DRY RUN] ' if dry_run else ''}BACKFILL  {addr}  →  opp #{opp.id}  sent_at={sent_dt.strftime('%Y-%m-%d %H:%M')}")

            if not dry_run:
                opp.zoho_pushed_at = sent_dt
                if contact.draft_sent_at is None:
                    contact.draft_sent_at = sent_dt
                updated += 1
            else:
                updated += 1

        if not dry_run:
            db.commit()

    print()
    print("── Result ──────────────────────────────────")
    print(f"  Sent addresses scanned          : {len(sent_by_email)}")
    print(f"  Already had zoho_pushed_at      : {already_ok}")
    print(f"  {'Would update' if dry_run else 'Updated'} zoho_pushed_at : {updated}")
    print(f"  No matching contact in DB       : {no_contact}")
    print(f"  No opportunity found            : {no_opp}")
    if dry_run:
        print()
        print("Run without --dry-run to apply.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync zoho_pushed_at in DB")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes")
    parser.add_argument("--from-zoho", action="store_true", help="Read Zoho Sent folder (requires READ scope)")
    parser.add_argument("--limit", type=int, default=500, help="Max Zoho messages to scan (--from-zoho only)")
    args = parser.parse_args()

    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            pass

    if args.from_zoho:
        run_sync_from_zoho(dry_run=args.dry_run, limit=args.limit)
    else:
        run_sync_from_db(dry_run=args.dry_run)
