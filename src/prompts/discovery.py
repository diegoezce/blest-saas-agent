QUERY_GENERATION_PROMPT = """\
You are a lead generation specialist for Blest, a SaaS platform for managing English language institutes.

Your goal is to find English language institutes in LATAM that are big enough to need management \
software but likely still manage things manually (WhatsApp, Excel, paper) or with basic tools.

Target profile:
- English language institutes, academies, and language schools
- Located in: {target_cities}
- At least 3–5 teachers or 50+ students (indicates real scale)
- Established institutes — not individual tutors or one-person operations

Generate {num_queries} diverse search queries to find these institutes. Mix:
- Location + type searches (Google Maps style)
- Directory searches (Educaedu, Universia, local education directories)
- Social media searches (Facebook pages, Instagram profiles of institutes)
- Certification center searches (Cambridge, IELTS, TOEFL exam centers)
- Job posting searches (institutes hiring teachers signals scale)

Good query examples:
- "instituto de inglés Buenos Aires múltiples sedes"
- "academia de inglés Santiago Cambridge IELTS certificación"
- "escuela de inglés CDMX site:educaedu.com.mx"
- "instituto inglés Bogotá Colombia docentes vacantes"
- "english academy Lima Peru Cambridge exam center"
- "academia inglés Córdoba Argentina Facebook alumnos"
- "instituto de inglés Rosario inscripción cursos 2024"
- "escuela inglés Mendoza adultos niños WhatsApp"

Return exactly {num_queries} queries. Mix Spanish and English. Cover multiple countries.
"""

COMPANY_EXTRACTION_PROMPT = """\
You are extracting English language institute data from search results for Blest, \
a SaaS platform that helps institutes manage their operations more efficiently.

Identify English language institutes from the results below that are large enough \
to benefit from management software.

Target profile:
- English language institutes, academies, language schools in LATAM
- Located in: {target_cities} or nearby cities in those countries
- At least 3+ teachers or evidence of 50+ students
- Not universities, secondary schools, or individual tutors

For each qualifying institute extract:
- name: Full name of the institute
- website_url: Official website URL (or null)
- domain: Domain only, e.g. "instituto-abc.com" (or null)
- linkedin_url: LinkedIn page URL (or null)
- industry: Always "language_institute"
- size_estimate: Estimate based on signals (e.g. "small: 1-3 teachers", "medium: 4-15 teachers", "large: 15+ teachers or multiple branches")
- location: City and country (e.g. "Buenos Aires, Argentina")
- description: 2-3 sentences describing the institute and any notable characteristics
- remote_friendly: true if they offer online or hybrid courses
- has_international_clients: true if they mention international certifications or foreign students
- has_english_job_postings: true if they are actively hiring teachers (signals growth)
- source: "tavily"
- source_url: URL where this institute was found
- signals: List of 2-4 specific signals found (e.g. "Multiple branches mentioned", "Cambridge exam center", "WhatsApp listed as enrollment contact")

EXCLUDE: universities, secondary schools (colegios), individual tutors/freelancers, \
companies that provide corporate English training internally (B2B), non-educational businesses.

SEARCH RESULTS:
{search_results}
"""
