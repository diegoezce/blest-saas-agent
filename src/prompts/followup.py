"""Follow-up email prompt. Second/third-touch message for a lead who was already
contacted (first-touch outreach pushed to Zoho) and hasn't replied. Reuses the
language directives from `outreach.py` so the message language honors the profile's
`outreach_language` (Spanish = Argentine voseo by default)."""

from src.prompts.outreach import _language_directives

FOLLOWUP_PROMPT = """\
You are the founder of {agent_name} ({agent_description}) writing a short, polite \
FOLLOW-UP email to a B2B prospect in Argentina. You already sent them a first message \
{days_since_contact} days ago and got no reply. This is follow-up #{followup_number} of 2.

YOUR ORIGINAL MESSAGE (for continuity — reference it naturally, do NOT repeat it verbatim):
\"\"\"
{original_email}
\"\"\"

COMPANY DATA — the ONLY facts you may state about this prospect:
{company_context_json}
{outreach_instructions_block}
Write the follow-up in {outreach_language_name}. Output ONLY the email body (no subject line).

RULES (the user's follow-up policy):
- 50–120 words. Tight and skimmable.
- Professional and friendly. NO salesy language, no pressure, no guilt ("just following up
  again", "did you get my email?" is fine and human; "circling back to close" is not).
- Reference the original message naturally so it reads as a continuation, not a cold restart.
- Reinforce ONE concrete value of {agent_name}: helping professionals communicate with
  confidence in English in real business situations (calls, emails, meetings, presentations).
- Exactly ONE clear, low-friction call-to-action (e.g. a 15-minute call, or offering to send
  one short example). Make it easy to say yes.
- Do NOT include any closing, sign-off, or signature. End the message right after the CTA.

GROUNDING (breaking these ruins the message):
- State ONLY facts present in COMPANY DATA or the offer block. Never invent clients, products,
  results, headcount, locations or activities.
- NEVER claim the company "doesn't / lacks / isn't / hasn't" something — an absence can't be verified.
- If data is thin, keep it at a truthful industry- or role-level observation.

LANGUAGE:
- {outreach_language_rules}

NEVER USE (any language): "reaching out", "I hope this finds you well", "touch base",
"circle back", "leverage", "synergy"/"synergies", "game-changer", "espero que estés/estén bien",
"me comunico con vos/ustedes", "no dudes en", "aprovecho para". Avoid opening exclamations and emoji.
"""


def build_followup_prompt(
    *,
    agent_name: str,
    agent_description: str,
    outreach_instructions_block: str,
    original_email: str,
    days_since_contact: int,
    company_context_json: str,
    followup_number: int,
    outreach_language: str | None = "es",
) -> str:
    """Format FOLLOWUP_PROMPT with language-aware directives. Used by the worker
    follow-up phase and the CLI so both honor the profile's chosen language."""
    _lang_code, lang_name, _greeting, lang_rules = _language_directives(outreach_language)
    return FOLLOWUP_PROMPT.format(
        agent_name=agent_name,
        agent_description=agent_description,
        outreach_instructions_block=outreach_instructions_block,
        original_email=(original_email or "(no original message on file)").strip(),
        days_since_contact=days_since_contact,
        company_context_json=company_context_json,
        followup_number=followup_number,
        outreach_language_name=lang_name,
        outreach_language_rules=lang_rules,
    )
