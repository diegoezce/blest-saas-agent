OUTREACH_PROMPT = """\
You are writing a first-touch outreach message for the founder of {agent_name}, {agent_description}.

{agent_name} helps companies {outreach_service_description}.

COMPANY AND INSIGHT DATA:
{company_and_insight_json}

Write TWO outreach messages:

1. LinkedIn message (max 110 words)
   - Conversational, direct, peer-to-peer
   - No subject line needed
   - Reference ONE specific thing about their business

2. Email (max 170 words + subject line)
   - Slightly more formal than LinkedIn
   - Subject line: max 8 words, curiosity-driven, no clickbait
   - Reference ONE specific thing about their business

BOTH MESSAGES MUST:
- Open with a genuine observation about their business (NOT a pitch)
- Feel human, not templated
- End with ONE low-commitment soft ask (e.g., "Would a 15-min call make sense?")
- Be written in English (this is intentional — it's a natural conversation starter)
- Be {outreach_tone} and helpful in tone

DO NOT USE: "I hope this finds you well", "synergies", "leverage", "game-changer", \
"reaching out", "I wanted to", "touch base", "circle back", "quick question"

Return both as separate draft objects with channel "linkedin" and "email" respectively.
"""
