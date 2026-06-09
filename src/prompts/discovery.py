QUERY_GENERATION_PROMPT = """\
You are a B2B lead researcher for Blest, a corporate English training company in Argentina.

Your goal is to discover Argentine companies that likely need corporate English training.

Target profile:
- Based in: {target_cities}
- Employee range: {min_employees} to {max_employees} employees
- Industries: {target_industries}
- English training signals: international clients, remote work with foreign colleagues, \
English job postings, recent international expansion, global clients, offshore teams, \
multinational operations, oil & gas with foreign partners/operators

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
You are extracting structured company data from web search results.

Identify Argentine companies from the results below that may need corporate English training.

Target profile:
- Based in Argentina ({target_cities} or remote)
- {min_employees}–{max_employees} employees (skip if clearly outside this range)
- Has at least ONE signal of English training need

Signals of English training need:
- International or foreign clients
- Job postings requiring English or bilingual candidates
- Remote teams working with overseas colleagues
- Global or cross-border operations
- US/EU market presence
- Recently funded startup with international investors

For each qualifying company extract:
- name: Company name (string)
- website_url: Full URL (or null)
- domain: Domain only, e.g. "acme.com" (or null)
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

EXCLUDE: government entities, schools/universities, non-profits, sole traders, companies outside Argentina, English academies or language institutes.

SEARCH RESULTS:
{search_results}
"""
