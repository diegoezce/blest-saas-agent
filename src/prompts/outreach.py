OUTREACH_PROMPT = """\
You are writing first-touch outreach messages for the founder of Blest, a corporate English \
training company in Argentina.

Blest helps Argentine company teams communicate more effectively in business English: \
emails, meetings, client calls, and presentations.

COMPANY AND INSIGHT DATA:
{company_and_insight_json}

Write FOUR outreach messages:

1. LinkedIn message in English (max 110 words, language: "en", channel: "linkedin")
2. LinkedIn message in Spanish (max 110 words, language: "es", channel: "linkedin")
3. Email in English (max 170 words + subject line, language: "en", channel: "email")
4. Email in Spanish (max 170 words + subject line, language: "es", channel: "email")

ALL MESSAGES MUST:
- Open with a genuine observation about their business (NOT a pitch)
- Feel human, not templated
- End with ONE low-commitment soft ask (e.g., "Would a 15-min call make sense?" / "¿Tendría sentido una llamada de 15 minutos?")
- Reference ONE specific thing about their business
- Be warm and helpful in tone

LinkedIn specifics:
- Conversational, direct, peer-to-peer
- No subject line needed (use empty string for subject_line)

Email specifics:
- Slightly more formal than LinkedIn
- Subject line: max 8 words, curiosity-driven, no clickbait

Spanish messages should feel native, not translated. Use Argentine professional register (vos/usted as appropriate).

DO NOT USE: "I hope this finds you well", "synergies", "leverage", "game-changer", \
"reaching out", "I wanted to", "touch base", "circle back", \
"espero que estés bien", "me pongo en contacto"

Return all four as separate draft objects.
"""
