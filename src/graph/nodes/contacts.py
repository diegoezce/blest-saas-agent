import logging
import anthropic
import instructor

from src.graph.state import AgentState
from src.schemas.outputs import CompanyContacts
from src.tools.search import search

logger = logging.getLogger(__name__)

_client = None

_CONTACTS_STATIC = """\
You are a B2B sales researcher identifying decision makers at Argentine companies for a \
corporate English training proposal.

PRIORITY ORDER OF TARGET ROLES:
1. Learning & Development (L&D) Manager / Talent Development / Capacitación
2. HR Manager / Gerente de Recursos Humanos / People Manager
3. Chief People Officer / VP People / Head of Talent
4. Operations Manager (for companies < 50 employees)
5. Founder / CEO / Managing Director (for companies with < 50 employees)

For each decision maker found, provide:
- name: Full name if found (null if not identifiable)
- role: Exact role title as found
- role_category: One of: hr, talent_ld, operations, founder, other
- linkedin_url: LinkedIn profile URL if found (null otherwise)
- email: Email address if found (null otherwise)
- confidence: "high" (directly confirmed by a reliable source), "medium" (inferred from context), "low" (likely role but not confirmed)
- notes: Brief explanation of where/how this person was found, or what was searched if not found

Return 1–2 contacts maximum. If no specific individual is found, include one entry with \
name=null and the most likely role at this type/size of company, with notes explaining \
what was searched.\
"""

_CONTACTS_DYNAMIC = """\
COMPANY: {company_name}

COMPANY CONTEXT AND SEARCH RESULTS:
{company_context}\
"""


def _llm():
    global _client
    if _client is None:
        from src.config import get_settings
        _client = instructor.from_anthropic(anthropic.Anthropic(api_key=get_settings().anthropic_api_key))
    return _client


def _build_company_context(company: dict) -> str:
    search_query = f'{company["name"]} Argentina HR manager LinkedIn recursos humanos'
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

    from src.config import get_settings
    cfg = get_settings()
    top_names = {s["company_name"] for s in scored[: cfg.max_companies_for_contacts]}
    companies_map = {c["name"]: c for c in state.get("companies", [])}

    logger.info(f"Step 3: Finding contacts for top {len(top_names)} companies...")
    contacts: list[dict] = []

    for company_name in top_names:
        company = companies_map.get(company_name)
        if not company:
            continue
        try:
            context = _build_company_context(company)
            result = _llm().messages.create(
                model=cfg.fast_model,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": _CONTACTS_STATIC,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "text",
                            "text": _CONTACTS_DYNAMIC.format(
                                company_name=company_name,
                                company_context=context,
                            ),
                        },
                    ],
                }],
                response_model=CompanyContacts,
            )
            contacts.append(result.model_dump())
            logger.debug(f"Found {len(result.contacts)} contacts for {company_name}")
        except Exception as e:
            logger.error(f"Contacts failed for {company_name}: {e}", exc_info=True)
            state["errors"].append(f"Contacts error ({company_name}): {e}")

    logger.info(f"Contacts found for {len(contacts)} companies")
    return {**state, "contacts": contacts}
