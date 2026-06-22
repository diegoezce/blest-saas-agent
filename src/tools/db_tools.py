import datetime
import logging
import re

from src.database.models import Company, Contact, ContactStatus, DailyReport, DiscoveryRun, Opportunity
from src.database.session import get_session
from src.graph.state import AgentState

logger = logging.getLogger(__name__)


def mark_company_contacted(session, company_id: int, method: str = "email") -> bool:
    """Ensure a company has a ContactStatus so it appears on the follow-up page.

    Called whenever an outreach draft is pushed to Zoho (worker + web buttons).
    Idempotent and non-destructive: if a ContactStatus already exists it is left
    untouched (preserves manually entered feedback/follow-up dates). Returns True
    only when a new record was created.
    """
    if not company_id:
        return False
    existing = session.get(ContactStatus, company_id)
    if existing:
        return False
    session.add(ContactStatus(
        company_id=company_id,
        contacted_at=datetime.datetime.utcnow(),
        contact_method=method,
    ))
    return True

# Legal/entity suffixes stripped when comparing company names for dedup
_LEGAL_SUFFIXES = (
    "sa", "s a", "srl", "s r l", "sas", "s a s", "saic", "sca",
    "inc", "llc", "ltd", "ltda", "co", "corp", "gmbh",
    "sociedad anonima", "sociedad de responsabilidad limitada",
)


def _normalize_domain(url: str | None) -> str | None:
    if not url:
        return None
    url = url.lower().strip()
    for prefix in ("https://www.", "http://www.", "https://", "http://", "www."):
        if url.startswith(prefix):
            url = url[len(prefix):]
    return url.split("/")[0].strip() or None


def normalize_company_name(name: str | None) -> str:
    """Normalize a company name for dedup: lowercase, drop punctuation, accents-light,
    collapse whitespace, strip trailing legal suffixes (SA, SRL, Inc, Ltd...)."""
    if not name:
        return ""
    s = name.lower().strip()
    s = re.sub(r"[.,/&]", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # strip one trailing legal suffix if present
    for suf in sorted(_LEGAL_SUFFIXES, key=len, reverse=True):
        if s.endswith(" " + suf):
            s = s[: -(len(suf) + 1)].strip()
            break
    return s


def _upsert_company(session, data: dict) -> int:
    domain = _normalize_domain(data.get("website_url") or data.get("domain"))

    existing = None
    if domain:
        existing = session.query(Company).filter_by(domain=domain).first()
    if not existing:
        existing = session.query(Company).filter(
            Company.name.ilike(data.get("name", ""))
        ).first()
    # Fall back to normalized-name match ("Acme S.A." == "Acme")
    if not existing:
        norm = normalize_company_name(data.get("name"))
        if norm:
            token = norm.split(" ")[0]
            candidates = (
                session.query(Company)
                .filter(Company.name.ilike(f"%{token}%"))
                .limit(100)
                .all()
            )
            for c in candidates:
                if normalize_company_name(c.name) == norm:
                    existing = c
                    break

    if existing:
        existing.last_updated_at = datetime.datetime.utcnow()
        if data.get("linkedin_url"):
            existing.linkedin_url = data["linkedin_url"]
        if data.get("description"):
            existing.description = data["description"]
        session.flush()
        return existing.id

    company = Company(
        name=data.get("name", "Unknown"),
        domain=domain,
        industry=data.get("industry"),
        size_estimate=data.get("size_estimate"),
        location=data.get("location"),
        description=data.get("description"),
        website_url=data.get("website_url"),
        linkedin_url=data.get("linkedin_url"),
        source=data.get("source", "tavily"),
        source_url=data.get("source_url"),
        raw_data=data,
    )
    session.add(company)
    session.flush()
    return company.id


def persist_run_node(state: AgentState) -> AgentState:
    run_id = state["run_id"]
    logger.info(f"Persisting run {run_id} to database...")

    try:
        with get_session() as session:
            score_map = {s["company_name"]: s for s in state.get("scored_opportunities", [])}
            insight_map = {i["company_name"]: i for i in state.get("insights", [])}
            outreach_map: dict[str, list] = {}
            for d in state.get("outreach_drafts", []):
                outreach_map.setdefault(d["company_name"], []).append(d)

            company_id_map: dict[str, int] = {}
            for company_data in state.get("companies", []):
                cid = _upsert_company(session, company_data)
                company_id_map[company_data["name"]] = cid

            for company_data in state.get("companies", []):
                name = company_data["name"]
                cid = company_id_map.get(name)
                scored = score_map.get(name, {})
                if not cid or not scored:
                    continue
                insight = insight_map.get(name, {})
                drafts = outreach_map.get(name, [])

                opp = Opportunity(
                    run_id=run_id,
                    company_id=cid,
                    score=scored.get("score", 0),
                    score_breakdown=scored.get("factors"),
                    score_explanation=scored.get("score_explanation"),
                    priority=scored.get("priority"),
                    insights=insight.get("why_they_need_training"),
                    evidence=insight.get("evidence_found"),
                    suggested_approach=insight.get("suggested_approach"),
                    conversation_angle=insight.get("conversation_starter"),
                    outreach_draft=drafts[0]["body"] if drafts else None,
                    outreach_subject=drafts[0].get("subject_line") if drafts else None,
                )
                try:
                    with session.begin_nested():
                        session.add(opp)
                except Exception as e:
                    logger.warning(f"Skipped opportunity for {name}: {e}")

            for contacts_data in state.get("contacts", []):
                cid = company_id_map.get(contacts_data["company_name"])
                if not cid:
                    continue
                for c in contacts_data.get("contacts", []):
                    name = (c.get("name") or "").strip()
                    # Allow nameless contacts: Layer 4 web search can find emails generically
                    # for companies where no named contact was discovered. Enrichment will
                    # search by company name (e.g., "The Functionary email").
                    linkedin = c.get("linkedin_url") or ""
                    # Dedup: match by LinkedIn URL (most reliable) or name within company
                    existing = None
                    if linkedin:
                        existing = session.query(Contact).filter_by(
                            company_id=cid, linkedin_url=linkedin
                        ).first()
                    if not existing and name:
                        existing = session.query(Contact).filter_by(
                            company_id=cid, name=name
                        ).first()
                    # For nameless placeholders, check if one already exists (avoid dupes)
                    if not existing and not name:
                        existing = session.query(Contact).filter_by(
                            company_id=cid, name=None
                        ).first()
                    if existing:
                        # Update fields that may have improved since last run
                        if c.get("role") and not existing.role:
                            existing.role = c["role"]
                        if linkedin and not existing.linkedin_url:
                            existing.linkedin_url = linkedin
                        if c.get("email") and not existing.email:
                            existing.email = c["email"]
                        continue
                    contact = Contact(
                        company_id=cid,
                        name=name,
                        role=c.get("role"),
                        role_category=c.get("role_category"),
                        linkedin_url=linkedin or None,
                        email=c.get("email"),
                        confidence_score={"high": 0.9, "medium": 0.6, "low": 0.3}.get(
                            c.get("confidence", "low"), 0.3
                        ),
                        source=c.get("source"),
                        raw_data=c,
                    )
                    session.add(contact)

            run = session.get(DiscoveryRun, run_id)
            if run:
                run.status = "completed"
                run.completed_at = datetime.datetime.utcnow()
                run.companies_found = len(state.get("companies", []))
                run.search_queries_used = state.get("search_queries", [])
                if state.get("profile_id"):
                    run.profile_id = state["profile_id"]

            scored_list = state.get("scored_opportunities", [])
            report_data = state.get("report", {})
            daily = DailyReport(
                run_id=run_id,
                report_date=datetime.date.fromisoformat(state["run_date"]),
                report_json=report_data or {"run_id": run_id, "run_date": state["run_date"]},
                top_opportunities=scored_list[:10],
                quick_wins=[s for s in scored_list if s.get("priority") == "quick_win"],
                strategic_opportunities=[s for s in scored_list if s.get("priority") == "strategic"],
                follow_up_suggestions=report_data.get("follow_up_suggestions", []),
            )
            session.add(daily)

        logger.info(f"Run {run_id} persisted successfully")

    except Exception as e:
        logger.error(f"Failed to persist run {run_id}: {e}", exc_info=True)
        state["errors"].append(f"DB persistence error: {e}")
        try:
            with get_session() as session:
                run = session.get(DiscoveryRun, run_id)
                if run:
                    run.status = "failed"
                    run.error_message = str(e)
        except Exception:
            pass

    return state


def generate_report_node(state: AgentState) -> AgentState:
    scored = state.get("scored_opportunities", [])
    contacts_list = state.get("contacts", [])
    top_contacts = []
    for c in contacts_list[:5]:
        top_contacts.extend(c.get("contacts", [])[:1])

    quick_wins = [s for s in scored if s.get("priority") == "quick_win"]
    strategic = [s for s in scored if s.get("priority") == "strategic"]

    follow_ups = []
    for scored_company in scored[:3]:
        name = scored_company["company_name"]
        follow_ups.append(f"Research {name} further — check their LinkedIn for current L&D activity")

    profile = state.get("profile", {})
    report = {
        "run_date": state["run_date"],
        "run_id": state["run_id"],
        "profile_id": state.get("profile_id"),
        "profile_name": profile.get("name", "Default") if profile else "Default",
        "total_companies_found": len(state.get("companies", [])),
        "quick_wins": quick_wins,
        "strategic_opportunities": strategic,
        "top_contacts": top_contacts,
        "top_insights": state.get("insights", []),
        "outreach_drafts": state.get("outreach_drafts", []),
        "all_contacts": state.get("contacts", []),
        "follow_up_suggestions": follow_ups,
    }

    return {**state, "report": report}
