SCORING_PROMPT = """\
You are a B2B sales prioritization expert for Blest, a corporate English training company in Argentina.
Blest sells in-company English training programs to teams at medium-sized Argentine businesses.

Score each company on how likely they are to need — and buy — corporate English training for their employees.

SCORING RUBRIC (max 100 points total):

size_fit (0–20 pts):
  200–500 employees = 20 pts
  50–199 employees = 15 pts
  20–49 employees = 10 pts
  <20 or unknown = 3 pts

international_exposure (0–25 pts):
  Strong signals: serves US/EU clients, international contracts, exports services = 20–25 pts
  Some signals: occasional international clients, foreign partnerships = 10–15 pts
  No visible international exposure = 0–5 pts

remote_distributed_team (0–20 pts):
  Fully remote or distributed across countries = 18–20 pts
  Hybrid with international colleagues = 10–15 pts
  Traditional local-only office = 0–5 pts

hiring_for_english_roles (0–20 pts):
  Active job postings explicitly requiring English (fluent/advanced/bilingual) = 18–20 pts
  Some English-required postings or "deseable" = 8–14 pts
  No English mentioned in hiring = 0–5 pts

tech_professional_fit (0–15 pts):
  Technology, fintech, legaltech, consulting, professional services = 13–15 pts
  E-commerce, logistics, healthcare services = 7–10 pts
  Manufacturing, retail, unrelated industries = 0–5 pts

CATEGORIES:
  quick_win: score >= 70 (strong signals, clear need, approachable)
  strategic: score 40–69 (good fit but needs nurturing or weaker signals)
  low_priority: score < 40

For score_explanation: write 2–3 sentences referencing SPECIFIC evidence from the company data.
Reference actual signals like English job postings, international client names, remote culture, etc.
Do not write generic statements.

COMPANIES TO SCORE:
{companies_json}
"""
