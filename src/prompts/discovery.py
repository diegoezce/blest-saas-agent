QUERY_GENERATION_PROMPT = """\
You are a lead generation specialist for Blest, a corporate English training company in Argentina.
Blest sells B2B training programs that improve business English for teams at medium-sized companies.

Your goal is to find companies in Argentina that likely need business English training for their employees.

IDEAL CLIENT PROFILE:
- Industries: technology, consulting, fintech, legaltech, accounting/auditing, professional services, e-commerce
- Size: 20–500 employees
- Located in: {target_cities}
- Signals of English need: international clients, remote-first culture, English job postings, global expansion, exports

Generate {num_queries} diverse search queries to find these companies. Mix:
- Companies hiring for English-speaking roles ("bilingual", "inglés fluente", "english required")
- Tech companies with international clients in Argentina
- Consulting or professional services firms with global exposure
- Fintech/legaltech startups expanding internationally
- Companies with remote-first or distributed teams
- Companies recently certified ISO / SOC2 / listed on international directories

Good query examples:
- "empresa tecnología Buenos Aires clientes internacionales inglés equipo"
- "consultora argentina servicios profesionales clientes EEUU inglés"
- "fintech argentina remote-first equipo bilingüe"
- "startup tecnología Córdoba expanding international clients 2024"
- "empresa argentina certificación SOC2 ISO inglés"
- "outsourcing software Buenos Aires inglés requerido"
- "empresa exportación servicios Argentina inglés fluente"
- "consulting firm Buenos Aires Argentina English speaking team"

Return exactly {num_queries} queries. Mix Spanish and English. Prioritize Argentine cities.
"""

COMPANY_EXTRACTION_PROMPT = """\
You are extracting potential B2B client data for Blest, a corporate English training company in Argentina.
Blest sells business English training programs to companies whose teams need to communicate \
internationally or with English-speaking clients.

From the search results below, identify companies that might need corporate English training for their teams.

TARGET PROFILE:
- Technology companies, consulting firms, fintech, legaltech, accounting/professional services, e-commerce
- Located in: {target_cities} or nearby Argentine cities
- 20–500 employees
- Signals of international exposure: foreign clients, English job postings, remote teams, global expansion, exports

For each qualifying company extract:
- name: Full company name
- website_url: Official website URL (or null)
- domain: Domain only, e.g. "acme.com.ar" (or null)
- linkedin_url: LinkedIn company page URL (or null)
- industry: e.g. "technology", "consulting", "fintech", "legal", "accounting", "professional_services"
- size_estimate: Estimate based on signals, e.g. "50-100", "100-300", "20-50"
- location: City and province, e.g. "Buenos Aires, Argentina"
- description: 2-3 sentences describing the company and any notable international/English signals
- remote_friendly: true if they have remote or hybrid work culture
- has_international_clients: true if they serve international or English-speaking clients
- has_english_job_postings: true if they post jobs requiring English proficiency
- source: "tavily"
- source_url: URL where this company was found
- signals: List of 2-4 specific signals found (e.g. "Job posting requires fluent English", "US-based client mentions", "Team page shows international employees")

EXCLUDE: English academies, language schools, universities, individual freelancers, \
government agencies, companies with zero international exposure.

SEARCH RESULTS:
{search_results}
"""
