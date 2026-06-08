SCORING_PROMPT = """\
You are a SaaS sales prioritization expert for Blest, a management platform for English language institutes in LATAM.

Score each institute on how much they need management software AND how approachable they are as a prospect.

SCORING RUBRIC (max 100 points total):

tamaño_instituto (0–20 pts):
  15+ teachers or multiple branches = 20 pts
  5–14 teachers = 15 pts
  3–4 teachers = 10 pts
  1–2 teachers or unknown = 3 pts

señales_crecimiento (0–25 pts):
  Clear growth signals: new branch opened, launched online courses, hiring multiple teachers = 20–25 pts
  Some growth: added new course levels, growing social media following = 10–15 pts
  Stable but no visible growth = 0–5 pts

dolor_admin_visible (0–20 pts):
  Strong pain signals: WhatsApp as main enrollment channel, Excel/paper-based processes mentioned = 18–20 pts
  Some signals: basic website with no online enrollment, manual payment methods = 8–14 pts
  No visible admin pain (already uses software) = 0–5 pts

adopcion_tecnologica (0–15 pts):
  Uses some tech but not integrated (e.g., Zoom for classes + WhatsApp for admin) = 12–15 pts
  Basic web presence, email, no clear software = 6–10 pts
  No digital presence at all OR already uses robust management software = 0–3 pts

reputacion_establecida (0–10 pts):
  Many Google/Facebook reviews, 5+ years operating, well-known locally = 8–10 pts
  Some reviews, 2–5 years = 4–7 pts
  New institute or no reviews = 0–3 pts

señales_inversion (0–10 pts):
  Active investment signals: hiring teachers, launching new programs, opening new location = 8–10 pts
  Some investment: occasional new courses, small team growth = 4–7 pts
  No visible investment = 0–3 pts

CATEGORIES:
  quick_win: score >= 70 (established institute with clear admin pain, ready for a tool)
  strategic: score 40–69 (good fit but needs nurturing or has some blockers)
  low_priority: score < 40

For score_explanation: write 2–3 sentences referencing SPECIFIC evidence from the institute data.
Reference actual signals like WhatsApp enrollment, number of branches, Cambridge certification, etc.
Do not write generic statements.

INSTITUTES TO SCORE:
{companies_json}
"""
