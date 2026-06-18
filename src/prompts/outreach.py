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
- Hook (1 sentence): one specific, verifiable detail about THEIR business taken from COMPANY DATA \
(a signal, their market, what they build). It must feel researched, not templated.
- Bridge to value (1-2 sentences): connect that detail to ONE concrete outcome {agent_name} enables. \
One idea only — no feature lists, no buzzwords.
- Proof (optional, 1 short clause): include ONLY if the pitch gives you a TRUE credibility cue \
(a comparable client type or result). Otherwise omit it entirely.
- Ask (1 sentence): a single low-friction, specific CTA that's easy to say yes to \
(e.g. a 15-minute call next week, or offering to send one short example).
- Sign-off: a short, human sign-off from {agent_name}.

APPROACH (what makes this land):
- Earn the reply — the opening is about THEM, the ask is small. Never pitch in the first sentence.
- One clear idea per message; delete any sentence that doesn't move toward the ask.
- Read like a real person wrote it in two minutes: warm, direct, specific. Tone: {outreach_tone}.
- Subject line: specific and value- or curiosity-driven, never generic or salesy. \
No ALL CAPS, no emojis, no clickbait.

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
