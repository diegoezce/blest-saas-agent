import json
import logging
from datetime import datetime, timedelta

import anthropic
import instructor

from src.graph.state import AgentState
from src.prompts.discovery import QUERY_GENERATION_PROMPT, COMPANY_EXTRACTION_PROMPT
from src.schemas.outputs import SearchQueryList, CompanyList
from src.tools.search import batch_search
from src.tools.db_tools import normalize_company_name, _normalize_domain
from src.config import get_settings, get_profile_overrides

logger = logging.getLogger(__name__)

_client = None


def _llm():
    global _client
    if _client is None:
        _client = instructor.from_anthropic(anthropic.Anthropic(api_key=get_settings().anthropic_api_key))
    return _client


def _load_known_companies(rediscover_after_days: int) -> tuple[set[str], set[str]]:
    """Return (normalized_names, domains) of companies already in the DB.

    Companies already contacted are always excluded. If rediscover_after_days>0,
    a never-contacted company last seen longer ago than that is *omitted* from
    the known sets, allowing it to be re-discovered.
    """
    from src.database.session import get_session
    from src.database.models import Company, ContactStatus

    names: set[str] = set()
    domains: set[str] = set()
    cutoff = None
    if rediscover_after_days and rediscover_after_days > 0:
        cutoff = datetime.utcnow() - timedelta(days=rediscover_after_days)

    with get_session() as session:
        contacted = {cid for (cid,) in session.query(ContactStatus.company_id).all()}
        for comp in session.query(Company).all():
            if cutoff is not None and comp.id not in contacted:
                seen_at = comp.last_updated_at or comp.first_seen_at
                if seen_at and seen_at < cutoff:
                    continue  # stale + never contacted → allow re-discovery
            nn = normalize_company_name(comp.name)
            if nn:
                names.add(nn)
            nd = _normalize_domain(comp.domain)
            if nd:
                domains.add(nd)
    return names, domains


def run_discovery_node(state: AgentState) -> AgentState:
    logger.info("Step 1: Generating search queries and discovering companies...")

    try:
        cfg = get_settings()
        po = get_profile_overrides(state.get("profile"))
        agent_name = po["agent_company_name"]
        agent_desc = po["agent_description"]

        search_focus_block = ""
        if po.get("search_focus_terms"):
            search_focus_block = (
                f"- Search focus: {po['search_focus_terms']}\n"
                f"- Additional signals: {po['search_focus_terms']}"
            )

        query_resp = _llm().messages.create(
            model=cfg.fast_model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": QUERY_GENERATION_PROMPT.format(
                    num_queries=cfg.discovery_queries_per_run,
                    agent_name=agent_name,
                    agent_description=agent_desc,
                    target_cities=", ".join(po["target_cities_list"]),
                    target_industries=", ".join(po["target_industries_list"]),
                    min_employees=po["min_employees"],
                    max_employees=po["max_employees"],
                    search_focus=search_focus_block,
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
            f"Title: {r['title']}\nURL: {r['url']}\nContent: {r['content'][:500]}"
            for r in raw_results[:80]
        )

        industry_signals = ""
        if po["search_focus_terms"]:
            industry_signals = f"- Industry-specific signals: {po['search_focus_terms']}"

        company_resp = _llm().messages.create(
            model=cfg.fast_model,
            max_tokens=8192,
            messages=[{
                "role": "user",
                "content": COMPANY_EXTRACTION_PROMPT.format(
                    agent_name=agent_name,
                    agent_description=agent_desc,
                    search_results=results_text,
                    target_cities=", ".join(po["target_cities_list"]),
                    min_employees=po["min_employees"],
                    max_employees=po["max_employees"],
                    industry_signals=industry_signals,
                ),
            }],
            response_model=CompanyList,
        )

        # Dedup within this run using the same normalization the DB uses, so
        # "Grupo Acme", "Acme S.A." and "Acme" collapse to one candidate.
        seen_names: set[str] = set()
        unique_companies: list[dict] = []
        for company in company_resp.companies:
            key = normalize_company_name(company.name) or company.name.lower().strip()
            if key and key not in seen_names:
                seen_names.add(key)
                unique_companies.append(company.model_dump())

        # Drop companies already discovered in previous runs (across-run dedup),
        # so each run surfaces net-new leads instead of repeating known ones.
        if cfg.exclude_known_companies:
            known_names, known_domains = _load_known_companies(cfg.rediscover_after_days)
            kept: list[dict] = []
            for c in unique_companies:
                nname = normalize_company_name(c.get("name"))
                ndom = _normalize_domain(c.get("website_url") or c.get("domain"))
                if (nname and nname in known_names) or (ndom and ndom in known_domains):
                    continue
                kept.append(c)
            dropped = len(unique_companies) - len(kept)
            if dropped:
                logger.info(f"Excluded {dropped} already-known companies (already seen in prior runs)")
            unique_companies = kept

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
