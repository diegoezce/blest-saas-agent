OUTREACH_PROMPT = """\
You are writing first-touch B2B outreach for {agent_name}, {agent_description}.
{agent_name} helps companies {outreach_service_description}.

COMPANY DATA:
{company_and_insight_json}

Write exactly TWO messages:
1. EMAIL — include subject line (≤8 words) + body (≤150 words). Channel: "email"
2. LINKEDIN — no subject needed, body ≤90 words. Channel: "linkedin"

Rules:
- First sentence: one specific observation about THEIR business (from the data above)
- No pitch in opening — lead with what you noticed, not what you sell
- Close with one low-commitment ask (e.g. "Worth a 15-min chat?")
- Language: English. Tone: {outreach_tone}
- NEVER use: "reaching out", "hope this finds you", "touch base", "quick question", "leverage", "synergies", "game-changer"
"""
