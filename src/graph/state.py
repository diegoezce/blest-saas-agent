from typing import TypedDict


class AgentState(TypedDict):
    run_id: int
    run_date: str
    profile_id: int | None
    profile: dict | None
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
