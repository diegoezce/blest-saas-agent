"""Client intake: bilingual question set + profile draft generation prompt.

The public /intake/<token> form renders INTAKE_QUESTIONS in the client's language.
Answers are stored as JSONB keyed by each question's `key`, then converted into a
draft Profile by Claude via PROFILE_DRAFT_PROMPT + the ProfileDraft schema.
"""

# type: text | textarea | select. Select options: list of (value, label_es, label_en).
INTAKE_QUESTIONS = [
    {
        "key": "company_name",
        "es": "¿Cómo se llama tu empresa?",
        "en": "What's your company called?",
        "hint_es": "",
        "hint_en": "",
        "type": "text",
        "required": True,
    },
    {
        "key": "company_about",
        "es": "¿Qué hace tu empresa? Contanos en pocas líneas qué venden u ofrecen y a quién.",
        "en": "What does your company do? In a few lines, what do you sell or offer, and to whom?",
        "hint_es": "Ej.: 'Somos un estudio de asesoría contable e impositiva para pymes exportadoras.'",
        "hint_en": "E.g.: 'We are an accounting and tax advisory firm for exporting SMEs.'",
        "type": "textarea",
        "required": True,
    },
    {
        "key": "ideal_customer_industries",
        "es": "¿Quién es tu cliente ideal? ¿En qué rubros o industrias trabaja?",
        "en": "Who is your ideal customer? What industries are they in?",
        "hint_es": "Listá los rubros donde mejor funciona tu servicio (ej.: tecnología, agro, comercio exterior).",
        "hint_en": "List the industries where your service works best (e.g. technology, agriculture, foreign trade).",
        "type": "textarea",
        "required": True,
    },
    {
        "key": "ideal_customer_size",
        "es": "¿De qué tamaño son esas empresas? (cantidad aproximada de empleados, mínimo y máximo)",
        "en": "How big are those companies? (approximate employee count, minimum and maximum)",
        "hint_es": "Ej.: 'entre 10 y 200 empleados'",
        "hint_en": "E.g.: 'between 10 and 200 employees'",
        "type": "text",
        "required": True,
    },
    {
        "key": "ideal_customer_locations",
        "es": "¿En qué ciudades o regiones querés conseguir clientes?",
        "en": "In which cities or regions do you want to find clients?",
        "hint_es": "Ej.: 'Buenos Aires, Córdoba y Rosario' o 'todo el país'",
        "hint_en": "E.g.: 'Buenos Aires, Córdoba and Rosario' or 'the whole country'",
        "type": "text",
        "required": True,
    },
    {
        "key": "problems_value",
        "es": "¿Qué problemas les resolvés? ¿Por qué te eligen a vos y no a otro?",
        "en": "What problems do you solve for them? Why do they choose you over someone else?",
        "hint_es": "",
        "hint_en": "",
        "type": "textarea",
        "required": True,
    },
    {
        "key": "proof_points",
        "es": "¿Qué clientes actuales, resultados o casos de éxito podemos mencionar? (solo cosas 100% reales)",
        "en": "Which current clients, results, or success stories can we mention? (only things that are 100% true)",
        "hint_es": "Los emails solo van a mencionar lo que escribas acá. Si no querés nombrar clientes, dejalo vacío.",
        "hint_en": "The emails will only mention what you write here. If you'd rather not name clients, leave it empty.",
        "type": "textarea",
        "required": False,
    },
    {
        "key": "decision_makers",
        "es": "¿Quién es la persona indicada para hablar en esas empresas? (cargos o roles, no nombres)",
        "en": "Who is the right person to talk to at those companies? (job titles or roles, not names)",
        "hint_es": "Ej.: 'dueño o socio gerente', 'gerente de administración y finanzas'",
        "hint_en": "E.g.: 'owner or managing partner', 'head of finance and administration'",
        "type": "textarea",
        "required": True,
    },
    {
        "key": "dream_clients",
        "es": "Nombrá 2 o 3 empresas que serían clientes soñados.",
        "en": "Name 2 or 3 companies that would be dream clients.",
        "hint_es": "Nos ayuda a entender exactamente qué tipo de empresa buscar.",
        "hint_en": "It helps us understand exactly what kind of company to look for.",
        "type": "text",
        "required": False,
    },
    {
        "key": "competitors_diff",
        "es": "¿Quiénes son tus competidores y qué te diferencia de ellos?",
        "en": "Who are your competitors and what makes you different?",
        "hint_es": "",
        "hint_en": "",
        "type": "textarea",
        "required": False,
    },
    {
        "key": "email_tone",
        "es": "¿Cómo preferís que suenen los emails?",
        "en": "How should the emails sound?",
        "hint_es": "",
        "hint_en": "",
        "type": "select",
        "required": True,
        "options": [
            ("warm", "Cálido y cercano", "Warm and personable"),
            ("direct", "Directo y al punto", "Direct and to the point"),
            ("professional", "Profesional y formal", "Professional and formal"),
            ("referral", "Como una recomendación de un conocido", "Like a referral from someone they know"),
        ],
    },
    {
        "key": "email_language",
        "es": "¿En qué idioma hay que escribir los emails?",
        "en": "What language should the emails be written in?",
        "hint_es": "",
        "hint_en": "",
        "type": "select",
        "required": True,
        "options": [
            ("es", "Español", "Spanish"),
            ("en", "Inglés", "English"),
        ],
    },
    {
        "key": "avoid",
        "es": "¿Hay algo que NO haya que decir, prometer o exagerar en los emails?",
        "en": "Is there anything we should NOT say, promise, or exaggerate in the emails?",
        "hint_es": "Ej.: 'no prometer plazos', 'no mencionar precios', 'no comparar con competidores por nombre'",
        "hint_en": "E.g.: 'don't promise timelines', 'don't mention prices', 'don't name competitors'",
        "type": "textarea",
        "required": False,
    },
    {
        "key": "anything_else",
        "es": "¿Algo más que debamos saber? (opcional)",
        "en": "Anything else we should know? (optional)",
        "hint_es": "",
        "hint_en": "",
        "type": "textarea",
        "required": False,
    },
]


PROFILE_DRAFT_PROMPT = """You are configuring a B2B lead discovery agent for a new client company.
The client answered a plain-language intake questionnaire. Convert their answers into a
complete discovery profile following the exact conventions of the example profiles below.

## Client's intake answers (question → answer)

{answers_json}

## Example profiles (style references — match their conventions exactly)

Example 1:
- name: "Blest Learning"
- description: "Corporate English training for Argentine mid-to-large companies in tech, consulting, fintech, oil & gas and other industries."
- agent_company_name: "Blest"
- agent_description: "a corporate English training provider in Argentina"
- target_industries: "technology,consulting,fintech,legaltech,accounting,professional_services,oil_gas,energy"
- target_cities: "Buenos Aires,Córdoba,Rosario,Mendoza,Neuquén"
- min_employees: 20 / max_employees: 500
- search_focus_terms: "improve their team's business English: written correspondence, client calls, presentations, async collaboration with international teams"
- target_roles: "Learning & Development (L&D) Manager / Talent Development / Capacitación,\\nHR Manager / Gerente de Recursos Humanos / People Manager,\\nChief People Officer / VP People / Head of Talent,\\nOperations Manager (for companies < 50 employees),\\nFounder / CEO / Managing Director (for companies < 50 employees)"

Example 2:
- name: "Blest App"
- agent_description: "a SaaS platform for English academies and language institutes to manage their operations, students, billing, and teacher coordination"
- target_industries: "education,language_teaching,english_institutes,training_centers,academias_de_ingles,institutos_de_idiomas"
- target_cities: "Buenos Aires,Córdoba,Rosario,Mendoza,Neuquén,La Plata,Mar del Plata,Salta,Tucumán,Santa Fe"
- min_employees: 2 / max_employees: 30
- search_focus_terms: "help English academies and language institutes streamline their operations: manage student enrollment, scheduling, billing, teacher coordination, progress tracking, and multilevel group classes"
- target_roles: "Director / Owner / Founder of English Academy or Language Institute,\\nAcademic Director / Coordinador Académico de Instituto de Inglés,\\nAdministrative Manager / Administrador de Instituto de Idiomas,\\nHead of Studies / Jefe de Estudios de Academia de Inglés,\\nOperations Manager / Gerente Operativo de Instituto de Idiomas"

## Field conventions (follow strictly)

- name: the client's company name (from company_name).
- agent_company_name: the client's company name as it should appear in emails.
- agent_description: a lowercase English phrase that completes "<company> is ..." — e.g. "an accounting advisory firm for exporting SMEs in Argentina".
- description: 1–2 sentence internal summary of what this profile targets (English is fine).
- target_industries: comma-separated lowercase tokens with underscores (e.g. professional_services). Include useful Spanish synonyms as extra tokens when they improve search recall (like academias_de_ingles above).
- target_cities: comma-separated city names with proper capitalization. If the client said "todo el país" or similar, list the 8–10 largest Argentine cities.
- min_employees / max_employees: integers parsed from ideal_customer_size. If the client gave no numbers, estimate sensible bounds from context; if truly unknown, leave null.
- search_focus_terms: an English phrase describing what the client helps companies do, phrased like the examples ("help X do Y: ...", "improve their ..."). Built from company_about + problems_value.
- discovery_strategy: free-text search strategy in English. Infer from dream_clients, industries, and any ecosystem hints: what kinds of directories, associations, news signals, or intent signals to prioritize; whether to favor quality over quantity. 3–6 sentences.
- target_roles: one role per line, each with English/Spanish title variants separated by " / ". Include size-conditional roles like "(for companies < 50 employees)" when the size range spans small companies.
- outreach_tone: map email_tone directly (warm | direct | professional | referral).
- outreach_language: map email_language directly (es | en).
- outreach_instructions: written in English, the anti-hallucination lever for email drafting. Structure it as:
  1. Value props: what to emphasize (from problems_value, competitors_diff).
  2. Proof points: ONLY the clients/results/cases the client explicitly stated in proof_points. If proof_points is empty, write "No proof points available — do not mention specific clients, results, or numbers."
  3. A section starting "NEVER say/promise:" listing everything from the avoid answer, plus "never invent clients, results, metrics, or capabilities not listed above".
  Include anything relevant from anything_else.

## Hard rules

- Never invent facts, clients, results, or numbers that are not in the client's answers.
- Prefer leaving a field conservative/empty over fabricating specifics.
- Keep the client's meaning; you may sharpen wording but not add claims.
"""
