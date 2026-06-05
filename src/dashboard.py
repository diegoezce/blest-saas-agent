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

    # Outreach drafts (show top 2)
    if drafts:
        console.print("[bold green]✉️  Outreach Drafts (Top 2)[/bold green]")
        shown: set[str] = set()
        count = 0
        for draft in drafts:
            key = f"{draft.get('company_name')}_{draft.get('channel')}"
            if key in shown or count >= 4:
                continue
            shown.add(key)
            count += 1
            channel = draft.get("channel", "").upper()
            company = draft.get("company_name", "")
            subject = draft.get("subject_line", "")
            body = draft.get("body", "")
            title = f"[{channel}] {company}" + (f" — {subject}" if subject else "")
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


def render_last_run(target_date: date | None = None) -> None:
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
            return

        run = session.get(DiscoveryRun, report_row.run_id)
        render_report_from_data(report_row.report_json, run)


def render_node(state: AgentState) -> AgentState:
    try:
        render_report_from_data(state.get("report", {}))
    except Exception as e:
        logger.error(f"Dashboard render failed: {e}", exc_info=True)
    return {**state, "completed": True}
