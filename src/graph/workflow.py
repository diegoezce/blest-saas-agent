import logging
from langgraph.graph import StateGraph, END

from src.graph.state import AgentState
from src.graph.nodes.discovery import run_discovery_node
from src.graph.nodes.scoring import run_scoring_node
from src.graph.nodes.contacts import run_contacts_node
from src.graph.nodes.insights import run_insights_node
from src.graph.nodes.outreach import run_outreach_node
from src.tools.db_tools import generate_report_node, persist_run_node
from src.tools.run_events import record_run_event

logger = logging.getLogger(__name__)


_STEP_SUMMARIES = {
    "discovery": lambda s: f"Discovery completed: {len(s.get('companies', []))} companies found.",
    "scoring": lambda s: f"Scoring completed: {len(s.get('scored_opportunities', []))} companies scored.",
    "contacts": lambda s: f"Contact search completed for {len(s.get('contacts', []))} companies.",
    "insights": lambda s: f"Insights generated for {len(s.get('insights', []))} companies.",
    "outreach": lambda s: f"Outreach completed: {len(s.get('outreach_drafts', []))} drafts generated.",
    "report": lambda s: "Report generated.",
    "persist": lambda s: "Results saved to the database.",
}


def _tracked_node(step: str, label: str, node):
    def run(state: AgentState) -> AgentState:
        run_id = state.get("run_id")
        record_run_event(run_id, f"{label} started.", step=step)
        errors_before = len(state.get("errors", []))
        try:
            result = node(state)
        except Exception as exc:
            record_run_event(run_id, f"{label} failed: {exc}", level="error", step=step)
            raise

        record_run_event(run_id, _STEP_SUMMARIES[step](result), step=step)
        for error in result.get("errors", [])[errors_before:]:
            record_run_event(run_id, error, level="warning", step=step)
        return result

    return run


def _after_discovery(state: AgentState) -> str:
    if not state.get("companies"):
        logger.warning("No companies discovered — jumping to report generation")
        return "generate_report"
    return "score_opportunities"


def build_workflow():
    graph = StateGraph(AgentState)

    graph.add_node("discover_companies", _tracked_node("discovery", "Discovery", run_discovery_node))
    graph.add_node("score_opportunities", _tracked_node("scoring", "Scoring", run_scoring_node))
    graph.add_node("find_contacts", _tracked_node("contacts", "Contact search", run_contacts_node))
    graph.add_node("generate_insights", _tracked_node("insights", "Insight generation", run_insights_node))
    graph.add_node("generate_outreach", _tracked_node("outreach", "Outreach generation", run_outreach_node))
    graph.add_node("generate_report", _tracked_node("report", "Report generation", generate_report_node))
    graph.add_node("persist_to_db", _tracked_node("persist", "Database persistence", persist_run_node))

    graph.set_entry_point("discover_companies")

    graph.add_conditional_edges(
        "discover_companies",
        _after_discovery,
        {
            "score_opportunities": "score_opportunities",
            "generate_report": "generate_report",
        },
    )
    graph.add_edge("score_opportunities", "find_contacts")
    graph.add_edge("find_contacts", "generate_insights")
    graph.add_edge("generate_insights", "generate_outreach")
    graph.add_edge("generate_outreach", "generate_report")
    graph.add_edge("generate_report", "persist_to_db")
    graph.add_edge("persist_to_db", END)

    return graph.compile()
