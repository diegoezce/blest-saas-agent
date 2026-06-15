CONTACTS_PROMPT = """\
You are a B2B sales researcher identifying decision makers at Argentine companies for a \
{agent_description} proposal on behalf of {agent_name}.

COMPANY: {company_name}

PRIORITY ORDER OF TARGET ROLES:
{target_roles}

COMPANY CONTEXT AND SEARCH RESULTS:
{company_context}

For each decision maker found, provide:
- name: Full name of the ACTUAL person (REQUIRED — only include people whose real \
name you can identify; never invent or guess a name)
- role: Exact role title as found
- role_category: One of: founder, director, academic, admin, other
  (use "director" for HR / People / L&D managers and heads; "founder" for \
CEO / owner / managing director; "admin" for operations or administrative staff; \
"other" if unsure)
- linkedin_url: LinkedIn profile URL if found (null otherwise)
- email: Email address if found (null otherwise)
- confidence: "high" (directly confirmed by a reliable source), "medium" (inferred from context), "low" (likely role but not confirmed)
- notes: Brief explanation of where/how this person was found

Return up to 2 NAMED decision makers, best first. Only include a person if you can \
identify their real name. If you cannot find any named individual, return an EMPTY \
contacts list — do NOT fabricate a placeholder or a name=null entry.
"""


# Default target roles for Blest corporate English training
DEFAULT_TARGET_ROLES = """\
1. Learning & Development (L&D) Manager / Talent Development / Capacitación
2. HR Manager / Gerente de Recursos Humanos / People Manager
3. Chief People Officer / VP People / Head of Talent
4. Operations Manager (for companies < 50 employees)
5. Founder / CEO / Managing Director (for companies with < 50 employees)"""
