QUERY_GENERATION_PROMPT = """\
You are a B2B lead researcher for {agent_name}, {agent_description}.

Your goal is to discover companies that likely need {agent_name}'s services.

Target profile:
- Based in: {target_cities}
- Employee range: {min_employees} to {max_employees} employees
- Industries: {target_industries}
{search_focus}

Generate {num_queries} diverse web search queries to find these companies.
Mix Spanish and English. Cover different sources: LinkedIn, Bumeran, Computrabajo, Glassdoor,
Infobae, La Nación Tecnología, Cronista, Clutch.co, Crunchbase, G2.

Good query examples:
- "empresa tech Argentina contratan desarrolladores clientes EEUU remoto"
- "Argentina consulting firm English speaking roles Buenos Aires"
- "software company Buenos Aires bilingual job posting 2024"
- "empresa argentina expansión internacional inglés corporativo"
- site:linkedin.com/company Argentina technology "international clients"
- "empresa oil gas Argentina inglés operadores internacionales Neuquén Vaca Muerta"
- "oil and gas company Argentina English speaking engineers Patagonia"
- "empresa energía Argentina servicios petroleros inglés Shell Schlumberger"

Return exactly {num_queries} queries.
"""

COMPANY_EXTRACTION_PROMPT = """\
You are extracting structured company data from web search results on behalf of {agent_name}, {agent_description}.

Identify companies from the results below that may need {agent_name}'s services.

Target profile:
- Based in Argentina ({target_cities} or remote)
- {min_employees}–{max_employees} employees (skip if clearly outside this range)
- Has at least ONE signal of need

Signals of need:
- International or foreign clients
- Job postings requiring English or bilingual candidates
- Remote teams working with overseas colleagues
- Global or cross-border operations
- US/EU market presence
- Recently funded startup with international investors
{industry_signals}

For each qualifying company extract:
- name: Company name (string)
- website_url: Full URL of the company's OWN official site (or null)
- domain: Domain only, e.g. "acme.com" (or null)
  IMPORTANT: Always extract the company's official website domain when it
  appears anywhere in the results. Never use social media, job boards, news
  sites or directory links (linkedin.com, facebook.com, bumeran, computrabajo,
  paginasamarillas, crunchbase, etc.) as the domain — leave null if only those
  are present.
- linkedin_url: LinkedIn company page URL (or null)
- industry: One of: technology, consulting, accounting, fintech, legaltech, professional_services, oil_gas, energy, other
- size_estimate: e.g. "50-100" or "unknown"
- location: City in Argentina (e.g. "Buenos Aires")
- description: 1-2 sentence summary of what the company does
- remote_friendly: true/false based on evidence
- has_international_clients: true/false based on evidence
- has_english_job_postings: true/false based on evidence
- source: "tavily"
- source_url: The URL where this company was found
- signals: List of 1-3 specific evidence strings (e.g. "Job posting requires advanced English for US client support")

EXCLUDE: government entities, non-profits, sole traders, companies outside Argentina.

SEARCH RESULTS:
{search_results}
"""
