from typing import TypedDict


class AgentState(TypedDict):
    run_id: int
    run_date: str
    search_queries: list[str]
    raw_search_results: list[dict]
    companies: list[dict]
    scored_opportunities: list[dict]
    contacts: list[dict]
    insights: list[dict]
    outreach_drafts: list[dict]
    report: dict
    errors: list[str]
    completed: bool
