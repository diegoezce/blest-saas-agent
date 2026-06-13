OUTREACH_PROMPT = """\
You are writing first-touch B2B outreach for {agent_name}, {agent_description}.
{agent_name} helps companies {outreach_service_description}.

COMPANY DATA — the ONLY facts you may state about this prospect:
{company_and_insight_json}
{custom_instructions_block}
Write exactly TWO messages:
1. EMAIL — include subject line (≤8 words) + body (≤130 words). Channel: "email"
2. LINKEDIN — no subject needed, body ≤80 words. Channel: "linkedin"

GROUNDING (breaking these ruins the message):
- Reference ONLY facts present in COMPANY DATA above. Never invent clients, products,
  achievements, tech, headcount, locations or activities that are not stated.
- If a field is null or missing, do not mention it and do not guess.
- NEVER claim the company "doesn't", "lacks", "isn't" or "hasn't" done something —
  you cannot verify an absence, and guessing wrong destroys credibility.
- If the data is thin, open with a truthful observation at the industry/role level
  instead of a fabricated specific detail.

STYLE:
- First sentence: one specific, verifiable observation about THEIR business from the data.
- No pitch in opening — lead with what you noticed, not what you sell.
- Close with one low-commitment ask (e.g. "Worth a 15-min chat?").
- Language: English. Tone: {outreach_tone}
- NEVER use: "reaching out", "hope this finds you", "touch base", "quick question", "leverage", "synergies", "game-changer"
"""
