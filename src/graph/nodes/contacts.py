import logging
import anthropic
import instructor

from src.graph.state import AgentState
from src.prompts.contacts import CONTACTS_PROMPT, DEFAULT_TARGET_ROLES
from src.schemas.outputs import CompanyContacts
from src.tools.search import search
from src.config import get_settings, get_profile_overrides

logger = logging.getLogger(__name__)

_client = None


def _llm():
    global _client
    if _client is None:
        _client = instructor.from_anthropic(anthropic.Anthropic(api_key=get_settings().anthropic_api_key))
    return _client


def _build_company_context(company: dict, profile: dict | None) -> str:
    po = get_profile_overrides(profile)
    agent_name = po["agent_company_name"]

    search_query = f'{company["name"]} director dueño fundador LinkedIn contacto'
    results = search(search_query, max_results=5)
    lines = [
        f"Company: {company['name']}",
        f"Industry: {company.get('industry', 'unknown')}",
        f"Size: {company.get('size_estimate', 'unknown')}",
        f"Location: {company.get('location', 'Argentina')}",
        f"Website: {company.get('website_url', 'N/A')}",
        f"LinkedIn: {company.get('linkedin_url', 'N/A')}",
        "",
        "Search results:",
    ]
    for r in results:
        lines.append(f"- {r['title']} ({r['url']}): {r['content'][:300]}")
    return "\n".join(lines)


def run_contacts_node(state: AgentState) -> AgentState:
    scored = state.get("scored_opportunities", [])
    if not scored:
        logger.warning("No scored companies — skipping contacts")
        return {**state, "contacts": []}

    cfg = get_settings()
    po = get_profile_overrides(state.get("profile"))

    top_names = {s["company_name"] for s in scored[: cfg.max_companies_for_contacts]}
    companies_map = {c["name"]: c for c in state.get("companies", [])}

    logger.info(f"Step 3: Finding contacts for top {len(top_names)} companies...")
    contacts: list[dict] = []

    # Determine target roles from profile or default
    target_roles_text = DEFAULT_TARGET_ROLES
    if po.get("target_roles"):
        role_lines = []
        for i, role in enumerate(po["target_roles"].split(","), 1):
            role_lines.append(f"{i}. {role.strip()}")
        if role_lines:
            target_roles_text = "\n".join(role_lines)

    for company_name in top_names:
        company = companies_map.get(company_name)
        if not company:
            continue
        try:
            context = _build_company_context(company, state.get("profile"))
            result = _llm().messages.create(
                model=cfg.fast_model,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": CONTACTS_PROMPT.format(
                                agent_name=po["agent_company_name"],
                                agent_description=po["agent_description"],
                                company_name=company_name,
                                target_roles=target_roles_text,
                                company_context=context,
                            ),
                            "cache_control": {"type": "ephemeral"},
                        },
                    ],
                }],
                response_model=CompanyContacts,
            )

            # Fallback: if no named contacts found, create placeholder for enrichment
            if not result.contacts:
                result.contacts = [{
                    "name": None,
                    "role": "Unknown",
                    "role_category": "other",
                    "linkedin_url": None,
                    "email": None,
                    "confidence": "low",
                    "notes": "Placeholder: no named contacts found; enrichment will search generically",
                }]
                logger.info(f"No named contacts found for {company_name}, created placeholder")

            contacts.append(result.model_dump())
            logger.debug(f"Found {len(result.contacts)} contacts for {company_name}")
        except Exception as e:
            logger.error(f"Contacts failed for {company_name}: {e}", exc_info=True)
            state["errors"].append(f"Contacts error ({company_name}): {e}")

    logger.info(f"Contacts found for {len(contacts)} companies")
    return {**state, "contacts": contacts}
