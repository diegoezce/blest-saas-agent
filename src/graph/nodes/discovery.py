import json
import logging
import anthropic
import instructor

from src.graph.state import AgentState
from src.prompts.discovery import QUERY_GENERATION_PROMPT, COMPANY_EXTRACTION_PROMPT
from src.schemas.outputs import SearchQueryList, CompanyList
from src.tools.search import batch_search

logger = logging.getLogger(__name__)

_client = None


def _llm():
    global _client
    if _client is None:
        from src.config import get_settings
        _client = instructor.from_anthropic(anthropic.Anthropic(api_key=get_settings().anthropic_api_key))
    return _client


def run_discovery_node(state: AgentState) -> AgentState:
    logger.info("Step 1: Generating search queries and discovering companies...")

    try:
        from src.config import get_settings
        cfg = get_settings()

        query_resp = _llm().messages.create(
            model=cfg.fast_model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": QUERY_GENERATION_PROMPT.format(
                    num_queries=cfg.discovery_queries_per_run,
                    target_cities=", ".join(cfg.target_cities_list),
                    target_industries=", ".join(cfg.target_industries_list),
                    min_employees=cfg.min_employees,
                    max_employees=cfg.max_employees,
                ),
            }],
            response_model=SearchQueryList,
        )
        queries = query_resp.queries[: cfg.discovery_queries_per_run]
        logger.info(f"Generated {len(queries)} search queries")

        raw_results = batch_search(queries)

        if not raw_results:
            logger.warning("No search results returned — skipping company extraction")
            return {**state, "search_queries": queries, "raw_search_results": [], "companies": []}

        results_text = "\n\n---\n\n".join(
            f"Title: {r['title']}\nURL: {r['url']}\nContent: {r['content'][:600]}"
            for r in raw_results[:50]
        )

        company_resp = _llm().messages.create(
            model=cfg.fast_model,
            max_tokens=8192,
            messages=[{
                "role": "user",
                "content": COMPANY_EXTRACTION_PROMPT.format(
                    search_results=results_text,
                    target_cities=", ".join(cfg.target_cities_list),
                    min_employees=cfg.min_employees,
                    max_employees=cfg.max_employees,
                ),
            }],
            response_model=CompanyList,
        )

        seen_names: set[str] = set()
        unique_companies: list[dict] = []
        for company in company_resp.companies:
            key = company.name.lower().strip()
            if key not in seen_names:
                seen_names.add(key)
                unique_companies.append(company.model_dump())

        capped = unique_companies[: cfg.max_companies_to_score]
        logger.info(f"Discovered {len(capped)} unique companies")

        return {
            **state,
            "search_queries": queries,
            "raw_search_results": raw_results,
            "companies": capped,
        }

    except Exception as e:
        logger.error(f"Discovery node failed: {e}", exc_info=True)
        state["errors"].append(f"Discovery error: {e}")
        return {**state, "search_queries": [], "raw_search_results": [], "companies": []}
