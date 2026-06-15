import logging
from datetime import date

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from src.database.session import get_session
from src.database.models import DailyReport, DiscoveryRun, Opportunity, Company, Contact
from src.graph.state import AgentState

logger = logging.getLogger(__name__)
console = Console()


def _score_color(score: int) -> str:
    if score >= 70:
        return "bold green"
    if score >= 50:
        return "bold yellow"
    return "bold red"


def _priority_badge(priority: str) -> str:
    return {"quick_win": "[green]⚡ Quick Win[/green]", "strategic": "[yellow]📈 Strategic[/yellow]"}.get(
        priority, "[dim]Low Priority[/dim]"
    )


def render_report_from_data(report_data: dict, run: DiscoveryRun | None = None) -> None:
    console.rule(f"[bold blue]🎯 Blest Lead Discovery — {report_data.get('run_date', 'Today')}[/bold blue]")

    total = report_data.get("total_companies_found", 0)
    quick_wins = report_data.get("quick_wins", [])
    strategic = report_data.get("strategic_opportunities", [])
    insights = report_data.get("top_insights", [])
    drafts = report_data.get("outreach_drafts", [])
    follow_ups = report_data.get("follow_up_suggestions", [])

    summary = (
        f"[bold]{total}[/bold] companies found  •  "
        f"[green][bold]{len(quick_wins)}[/bold][/green] quick wins  •  "
        f"[yellow][bold]{len(strategic)}[/bold][/yellow] strategic  •  "
        f"[bold]{len(drafts)}[/bold] outreach drafts ready"
    )
    console.print(Panel(summary, title="Summary", border_style="blue"))
    console.print()

    # Top opportunities table
    all_scored = quick_wins + strategic
    if all_scored:
        table = Table(
            title="📊 Top Opportunities",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Rank", style="dim", width=5)
        table.add_column("Company", min_width=20)
        table.add_column("Score", justify="center", width=7)
        table.add_column("Priority", width=16)
        table.add_column("Why", min_width=40)

        for i, opp in enumerate(all_scored[:10], 1):
            score = opp.get("score", 0)
            table.add_row(
                str(i),
                opp.get("company_name", "—"),
                Text(str(score), style=_score_color(score)),
                _priority_badge(opp.get("priority", "")),
                opp.get("score_explanation", "")[:100] + "..." if len(opp.get("score_explanation", "")) > 100 else opp.get("score_explanation", ""),
            )
        console.print(table)
        console.print()

    # Insights
    if insights:
        console.print("[bold cyan]💡 Company Insights[/bold cyan]")
        for insight in insights[:5]:
            console.print(
                Panel(
                    f"[bold]Why they need training:[/bold]\n{insight.get('why_they_need_training', '')}\n\n"
                    f"[bold]Approach:[/bold] {insight.get('suggested_approach', '')}\n\n"
                    f"[bold]Conversation starter:[/bold] [italic]{insight.get('conversation_starter', '')}[/italic]",
                    title=f"[bold]{insight.get('company_name', '')}[/bold]",
                    border_style="cyan",
                )
            )
        console.print()

    # Outreach drafts grouped by company (show top 5)
    if drafts:
        console.print("[bold green]✉️  Outreach Drafts[/bold green]")
        by_company: dict[str, list] = {}
        for d in drafts:
            by_company.setdefault(d.get("company_name", ""), []).append(d)
        for company_name, company_drafts in list(by_company.items())[:5]:
            first = company_drafts[0]
            recipient_parts = []
            if first.get("contact_name"):
                role = first.get("contact_role", "")
                label = f"{first['contact_name']} ({role})" if role else first["contact_name"]
                recipient_parts.append(label)
            if first.get("contact_email"):
                recipient_parts.append(first["contact_email"])
            if first.get("contact_linkedin_url"):
                recipient_parts.append(first["contact_linkedin_url"])
            recipient_line = "  ·  ".join(recipient_parts) or "Destinatario desconocido"
            console.print(f"  [dim]Para:[/dim] {recipient_line}")
            for draft in company_drafts:
                channel = draft.get("channel", "").upper()
                subject = draft.get("subject_line", "")
                body = draft.get("body", "")
                title = f"[{channel}] {company_name}" + (f" — {subject}" if subject else "")
                console.print(Panel(body, title=title, border_style="green"))
        console.print()

    # Follow-up suggestions
    if follow_ups:
        console.print("[bold yellow]📋 Follow-Up Suggestions[/bold yellow]")
        for suggestion in follow_ups:
            console.print(f"  • {suggestion}")
        console.print()

    if run:
        console.print(f"[dim]Run ID: {run.id}  |  Completed: {run.completed_at}[/dim]")


def _enrich_drafts_from_db(session, report_json: dict) -> dict:
    """Overlay LIVE contact data onto the cached report drafts.

    Always refreshes `email_status`/`email_source`/etc. from the DB so changes made
    after the run (enrichment, bounce marking) show up — matching each draft to a
    contact by its email first (precise), falling back to the best contact for the
    company. Also fills missing contact info for drafts that have none.
    """
    drafts = report_json.get("outreach_drafts", [])
    if not drafts:
        return report_json

    # email -> live Contact (to overlay current status precisely, incl. "bounced")
    email_map: dict[str, Contact] = {
        (c.email or "").lower(): c
        for c in session.query(Contact).filter(Contact.email.isnot(None)).all()
    }

    # Best contact per company — only needed to fill drafts that lack contact info
    need_best = any(
        not d.get("contact_email") and not d.get("contact_linkedin_url") for d in drafts
    )
    best_by_company: dict[str, Contact] = {}
    if need_best:
        for company in session.query(Company).all():
            best = (
                session.query(Contact)
                .filter_by(company_id=company.id)
                .order_by(Contact.confidence_score.desc())
                .first()
            )
            if best:
                best_by_company[company.name] = best

    enriched_drafts = []
    for d in drafts:
        if not d.get("contact_email") and not d.get("contact_linkedin_url"):
            contact = best_by_company.get(d.get("company_name", ""))
            if contact:
                d = {
                    **d,
                    "contact_name": d.get("contact_name") or contact.name,
                    "contact_role": d.get("contact_role") or contact.role,
                    "contact_email": contact.email,
                    "contact_linkedin_url": contact.linkedin_url,
                }
        live = email_map.get((d.get("contact_email") or "").lower()) \
            or best_by_company.get(d.get("company_name", ""))
        if live:
            d = {
                **d,
                "contact_id": live.id,
                "email_status": live.email_status,
                "email_source": live.email_source,
                "phone_whatsapp": live.phone_whatsapp,
                "enrichment_log": live.enrichment_log,
            }
        enriched_drafts.append(d)
    return {**report_json, "outreach_drafts": enriched_drafts}


def render_last_run(target_date: date | None = None) -> dict | None:
    with get_session() as session:
        query = session.query(DailyReport).join(DiscoveryRun)
        if target_date:
            query = query.filter(DailyReport.report_date == target_date)
        else:
            query = query.order_by(DailyReport.created_at.desc())

        report_row = query.first()

        if not report_row:
            label = str(target_date) if target_date else "any date"
            console.print(f"[red]No report found for {label}. Run the agent first.[/red]")
            return None

        run = session.get(DiscoveryRun, report_row.run_id)
        report_data = _enrich_drafts_from_db(session, report_row.report_json)
        render_report_from_data(report_data, run)
        return report_data


def render_node(state: AgentState) -> AgentState:
    try:
        render_report_from_data(state.get("report", {}))
    except Exception as e:
        logger.error(f"Dashboard render failed: {e}", exc_info=True)
    return {**state, "completed": True}
