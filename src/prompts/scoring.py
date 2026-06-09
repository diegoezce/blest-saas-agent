SCORING_PROMPT = """\
You are a B2B sales prioritization expert for {agent_name}, {agent_description}.

Score each company on how much they need {agent_name}'s services AND how approachable they are.

SCORING RUBRIC (max 100 points total):

{scoring_rubric}

CATEGORIES:
  quick_win: score >= 70
  strategic: score 40–69
  low_priority: score < 40

For score_explanation: write 2–3 sentences referencing SPECIFIC evidence from the company data.
Do not write generic statements. Reference actual signals like job postings, client mentions, etc.

COMPANIES TO SCORE:
{companies_json}
"""


# Default scoring rubric for Blest corporate English training
DEFAULT_SCORING_RUBRIC = """\
company_size (0–20 pts):
  50–200 employees = 20 pts
  200–500 employees = 15 pts
  20–50 employees = 12 pts
  <20 or >500 employees = 5 pts
  unknown = 10 pts

international_exposure (0–25 pts):
  Clear evidence of international clients or global operations = 20–25 pts
  Some hints of international work = 10–15 pts
  Minimal signals = 0–5 pts

remote_workforce (0–20 pts):
  Remote-first or fully distributed team = 20 pts
  Hybrid with international colleagues = 10–15 pts
  Traditional in-office only = 3–5 pts

hiring_activity (0–15 pts):
  Active English-language job postings or bilingual roles = 12–15 pts
  Some English role requirements = 5–8 pts
  No evidence of English hiring = 0–2 pts

tech_adoption (0–10 pts):
  SaaS product company or tech-forward consultancy = 8–10 pts
  Modern tooling, digital-first = 5–7 pts
  Traditional/legacy = 2–4 pts

english_training_signals (0–10 pts):
  Explicit L&D investment, training culture, English mentioned = 8–10 pts
  Implicit signals (international meetings, English docs) = 4–6 pts
  No signals = 0–2 pts"""
