import logging

from src.graph.state import AgentState
from src.config import get_settings, get_profile_overrides

logger = logging.getLogger(__name__)


def _parse_size(size_str: str) -> int:
    """Parse '50-100', '200+', '500' → approximate midpoint. Returns -1 if unknown."""
    if not size_str or size_str.lower() in ("unknown", ""):
        return -1
    s = size_str.replace("+", "").replace(" ", "").replace(",", "")
    if "-" in s:
        parts = s.split("-")
        try:
            return (int(parts[0]) + int(parts[-1])) // 2
        except ValueError:
            pass
    try:
        return int(s)
    except ValueError:
        return -1


def _score_company(company: dict, min_emp: int, max_emp: int) -> dict:
    score = 0
    breakdown: dict[str, int] = {}

    # Company size (0-20)
    emp = _parse_size(company.get("size_estimate", "unknown"))
    if emp < 0:
        size_pts = 10
    elif min_emp <= emp <= max_emp:
        if 50 <= emp <= 200:
            size_pts = 20
        elif 200 < emp <= 500:
            size_pts = 15
        elif min_emp <= emp < 50:
            size_pts = 12
        else:
            size_pts = 8
    else:
        size_pts = 3
    breakdown["company_size"] = size_pts
    score += size_pts

    # International exposure (0-25)
    if company.get("has_international_clients"):
        intl_pts = 25
    elif len(company.get("signals", [])) >= 2:
        intl_pts = 12
    elif len(company.get("signals", [])) == 1:
        intl_pts = 6
    else:
        intl_pts = 0
    breakdown["international_exposure"] = intl_pts
    score += intl_pts

    # Remote workforce (0-20)
    remote_pts = 20 if company.get("remote_friendly") else 5
    breakdown["remote_workforce"] = remote_pts
    score += remote_pts

    # English hiring activity (0-15)
    eng_hire_pts = 15 if company.get("has_english_job_postings") else 0
    breakdown["hiring_activity"] = eng_hire_pts
    score += eng_hire_pts

    # Industry/tech adoption (0-10)
    tech_industries = {"technology", "fintech", "legaltech", "consulting"}
    ind = company.get("industry", "").lower()
    tech_pts = 10 if ind in tech_industries else 5
    breakdown["tech_adoption"] = tech_pts
    score += tech_pts

    # English signals in description + signals text (0-10)
    text = " ".join([
        company.get("description", ""),
        *company.get("signals", []),
    ]).lower()
    eng_keywords = [
        "english", "inglés", "bilingual", "bilingüe",
        "international", "global", "eeuu", "us client", "clients abroad",
    ]
    eng_pts = 10 if any(k in text for k in eng_keywords) else 0
    breakdown["english_training_signals"] = eng_pts
    score += eng_pts

    score = min(score, 100)

    # Hard cap for companies clearly above the profile's size ceiling.
    # A 1,000+ employee enterprise (e.g. Globant) otherwise scores 90+ from the
    # international/remote/tech buckets, but a cold email to one employee there
    # has a structurally near-zero response rate. Force it to low_priority so the
    # worker's push floor (score >= 40) skips it.
    if emp >= 0 and emp > max_emp:
        score = min(score, 35)

    if score >= 70:
        priority = "quick_win"
    elif score >= 40:
        priority = "strategic"
    else:
        priority = "low_priority"

    positives = []
    if company.get("has_international_clients"):
        positives.append("international clients")
    if company.get("has_english_job_postings"):
        positives.append("English job postings")
    if company.get("remote_friendly"):
        positives.append("remote-friendly")
    explanation = (
        f"Score {score}: {', '.join(positives)}."
        if positives
        else f"Score {score}: limited English signals detected."
    )

    return {
        "company_name": company["name"],
        "score": score,
        "score_explanation": explanation,
        "score_breakdown": breakdown,
        "priority": priority,
    }


def run_scoring_node(state: AgentState) -> AgentState:
    companies = state.get("companies", [])
    if not companies:
        logger.warning("No companies to score")
        return {**state, "scored_opportunities": []}

    cfg = get_settings()
    po = get_profile_overrides(state.get("profile"))
    min_emp = po.get("min_employees", cfg.min_employees)
    max_emp = po.get("max_employees", cfg.max_employees)

    logger.info(f"Step 2: Rule-based scoring {len(companies)} companies (no AI call)...")

    scored = [_score_company(c, min_emp, max_emp) for c in companies]
    scored.sort(key=lambda x: x["score"], reverse=True)

    quick_wins = sum(1 for s in scored if s["priority"] == "quick_win")
    strategic = sum(1 for s in scored if s["priority"] == "strategic")
    logger.info(f"Scored {len(scored)} companies — {quick_wins} quick wins, {strategic} strategic")

    return {**state, "scored_opportunities": scored}
