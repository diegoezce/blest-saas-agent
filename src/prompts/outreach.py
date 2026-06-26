OUTREACH_PROMPT = """\
You are the founder of {agent_name} ({agent_description}) writing a first-touch B2B message \
to a prospect company in Argentina. {agent_name} helps companies {outreach_service_description}.

COMPANY DATA — the ONLY facts you may state about this prospect:
{company_and_insight_json}
{custom_instructions_block}
Produce exactly TWO messages, BOTH written in {outreach_language_name}:
1. EMAIL    — subject line (≤7 words) + body (~90-110 words). channel "email", language "{outreach_language}".
2. LINKEDIN — no subject, body ≤55 words. channel "linkedin", language "{outreach_language}".

EMAIL SHAPE (follow this flow; do NOT print labels or bullet markers):
- Greeting: "{greeting}" + the contact's first name if `contact_name` is set; otherwise a brief, role-appropriate greeting.
- Hook (1-2 sentences): Name the REAL problem or tension the prospect lives in their daily work — NOT a description of their industry or how their business works. Structure: specific tension or risk in their context → concrete consequence if not resolved. Direct, no condescension. Never explain to the recipient something they already know about their own job.
  ✓ "El inglés técnico-legal tiene su propio vocabulario — y una ambigüedad en una carta de oficina o una llamada con un licenciatario extranjero puede costar caro."
  ✗ "Un estudio enfocado en patentes y tecnología opera en un entorno donde el inglés no es opcional: cartas de oficina, correspondencia con examinadores, llamadas con licenciatarios o socios del exterior."
- Bridge to value (1-2 sentences): connect that tension to ONE concrete outcome {agent_name} enables. \
One idea only — no feature lists, no buzzwords.
- Proof (optional, 1 short clause): include ONLY if the pitch gives you a TRUE credibility cue \
(a comparable client type or result). Otherwise omit it entirely.
- Ask (1 sentence): a single low-friction, specific CTA that's easy to say yes to \
(e.g. a 15-minute call next week, or offering to send one short example).
- CRITICAL: The last sentence of the email body MUST be the CTA. Stop there. Do not add anything after it — no sign-off, no name, no title, no company name, no URL, no website, no phone, no "Más info en", no "Para más información", no "Podés conocer más en", no "te invito a visitar", no social media, no "del equipo", no "Mariela", nothing. The real sender signature is appended automatically — any text you add after the CTA will be deleted.

APPROACH (what makes this land):
- Earn the reply — the opening is about THEM, the ask is small. Never pitch in the first sentence.
- One clear idea per message; delete any sentence that doesn't move toward the ask.
- Read like a real person wrote it in two minutes: warm, direct, specific. Tone: {outreach_tone}.
- Subject line: specific and value- or curiosity-driven, never generic or salesy. \
No ALL CAPS, no emojis, no clickbait.

EXAMPLE — study this email and match its style exactly:
Subject: Inglés técnico-legal para equipos de IP

Hola Martín,

El inglés técnico-legal tiene su propio vocabulario — y una ambigüedad en una carta de oficina o una llamada con un licenciatario extranjero puede costar caro.

En Blest Learning trabajamos con equipos legales y técnicos para reforzar exactamente ese inglés: el de la negociación, la redacción formal y la representación ante clientes internacionales.

¿Tendría sentido coordinar 15 minutos la semana que viene para explorar si hay algo concreto en lo que podemos ayudar?
---
Note what makes this work: the hook names a real risk (ambiguity → costly mistake), not a description of the industry. The bridge is one specific outcome. The CTA is low-friction and ends the message completely.

GROUNDING (breaking these ruins the message):
- State ONLY facts present in COMPANY DATA or the pitch. Never invent clients, products, results, \
tech, headcount, locations or activities.
- If a field is null/missing, don't mention it and don't guess.
- NEVER claim the company "doesn't / lacks / isn't / hasn't" something — an absence can't be verified.
- If the data is thin, open with a truthful industry- or role-level observation instead of a fabricated specific.

LANGUAGE:
- {outreach_language_rules}

NEVER USE (any language): "reaching out", "I hope this finds you well", "touch base", "circle back", \
"quick question", "leverage", "synergy"/"synergies", "game-changer", "espero que estés/estén bien", \
"me comunico con vos/ustedes", "no dudes en", "aprovecho para", "potenciar sinergias". \
Avoid opening exclamations and emoji.
"""


def _language_directives(language: str | None) -> tuple[str, str, str, str]:
    """Return (lang_code, lang_name, greeting, rules) for the outreach language."""
    if (language or "es").strip().lower().startswith("en"):
        return (
            "en",
            "English",
            "Hi",
            "Write in natural, professional English. Warm but concise; contractions are fine. "
            "Avoid corporate jargon, over-formality and literal translations.",
        )
    return (
        "es",
        "Spanish (Argentina)",
        "Hola",
        "Escribí en español rioplatense natural y profesional, usando voseo "
        "(\"tenés\", \"podés\", \"te interesa\", \"contame\"). Cercano pero serio; "
        "sin formalismos acartonados (\"Estimado/a\", \"Cordialmente\") y sin traducir "
        "literal del inglés. "
        "ORTOGRAFÍA Y GRAMÁTICA IMPECABLES: usá ÚNICAMENTE palabras que existan en español "
        "(p. ej. \"malentendidos\", NO \"malinterpretidos\"); jamás inventes términos ni "
        "castellanices palabras en inglés; ante la menor duda con una palabra, reemplazala por "
        "una más simple y correcta. "
        "Puntuación correcta: abrí toda pregunta con \"¿\" y cerrala con \"?\"; "
        "no uses signos de exclamación ni de apertura (\"¡\") ni de cierre (\"!\"). "
        "Escribí en español; podés usar un término en inglés solo si es estándar y necesario "
        "(p. ej. \"business English\", \"deadline\"), pero NUNCA mezcles artículos o verbos con "
        "inglés (mal: \"el English\", \"los deals\", \"mercado US\"; bien: \"el inglés\", "
        "\"las oportunidades\", \"el mercado estadounidense\").",
    )


def build_outreach_prompt(
    *,
    agent_name: str,
    agent_description: str,
    outreach_service_description: str,
    outreach_tone: str,
    company_and_insight_json: str,
    custom_instructions_block: str,
    outreach_language: str | None = "es",
) -> str:
    """Format OUTREACH_PROMPT with language-aware directives. Used by the outreach
    node and the worker so both honor the profile's chosen language."""
    lang_code, lang_name, greeting, lang_rules = _language_directives(outreach_language)
    return OUTREACH_PROMPT.format(
        agent_name=agent_name,
        agent_description=agent_description,
        outreach_service_description=outreach_service_description,
        outreach_tone=outreach_tone,
        company_and_insight_json=company_and_insight_json,
        custom_instructions_block=custom_instructions_block,
        outreach_language=lang_code,
        outreach_language_name=lang_name,
        greeting=greeting,
        outreach_language_rules=lang_rules,
    )
