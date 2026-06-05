import logging
from langgraph.graph import StateGraph, END

from src.graph.state import AgentState
from src.graph.nodes.discovery import run_discovery_node
from src.graph.nodes.scoring import run_scoring_node
from src.graph.nodes.contacts import run_contacts_node
from src.graph.nodes.insights import run_insights_node
from src.graph.nodes.outreach import run_outreach_node
from src.tools.db_tools import generate_report_node, persist_run_node

logger = logging.getLogger(__name__)


def _after_discovery(state: AgentState) -> str:
    if not state.get("companies"):
        logger.warning("No companies discovered — jumping to report generation")
        return "generate_report"
    return "score_opportunities"


def build_workflow():
    graph = StateGraph(AgentState)

    graph.add_node("discover_companies", run_discovery_node)
    graph.add_node("score_opportunities", run_scoring_node)
    graph.add_node("find_contacts", run_contacts_node)
    graph.add_node("generate_insights", run_insights_node)
    graph.add_node("generate_outreach", run_outreach_node)
    graph.add_node("generate_report", generate_report_node)
    graph.add_node("persist_to_db", persist_run_node)

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
