import datetime
import logging

from src.database.models import Company, Contact, DailyReport, DiscoveryRun, Opportunity
from src.database.session import get_session
from src.graph.state import AgentState

logger = logging.getLogger(__name__)


def _normalize_domain(url: str | None) -> str | None:
    if not url:
        return None
    url = url.lower().strip()
    for prefix in ("https://www.", "http://www.", "https://", "http://", "www."):
        if url.startswith(prefix):
            url = url[len(prefix):]
    return url.split("/")[0].strip() or None


def _upsert_company(session, data: dict) -> int:
    domain = _normalize_domain(data.get("website_url") or data.get("domain"))

    existing = None
    if domain:
        existing = session.query(Company).filter_by(domain=domain).first()
    if not existing:
        existing = session.query(Company).filter(
            Company.name.ilike(data.get("name", ""))
        ).first()

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
                    contact = Contact(
                        company_id=cid,
                        name=c.get("name"),
                        role=c.get("role"),
                        role_category=c.get("role_category"),
                        linkedin_url=c.get("linkedin_url"),
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

    report = {
        "run_date": state["run_date"],
        "run_id": state["run_id"],
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
