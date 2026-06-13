from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI Models
    anthropic_api_key: str
    fast_model: str = "claude-haiku-4-5-20251001"
    reasoning_model: str = "claude-sonnet-4-6"

    # Search
    tavily_api_key: str = ""
    tavily_max_results: int = 10
    tavily_search_depth: str = "basic"

    # Database
    database_url: str = "postgresql+psycopg2://blest:blest@localhost:5432/blest_leads"

    # Web UI
    web_password: str = "blest2024"
    trigger_password: str = "blest2024"

    # Scheduler
    schedule_time: str = "08:00"
    schedule_days: str = "mon-thu"
    schedule_profile_name: str = ""
    scheduler_timezone: str = "America/Argentina/Buenos_Aires"

    # Workflow tuning
    discovery_queries_per_run: int = 12
    max_companies_to_score: int = 50
    max_companies_for_contacts: int = 30
    max_companies_for_insights: int = 0
    max_companies_for_outreach: int = 20

    # Business targeting (defaults — overridable by Profile)
    target_cities: str = "Buenos Aires,Córdoba,Rosario,Mendoza,Neuquén"
    target_industries: str = "technology,consulting,fintech,legaltech,accounting,professional_services,oil_gas,energy"
    min_employees: int = 20
    max_employees: int = 500

    # Zoho Mail integration
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_account_id: str = ""
    zoho_from_address: str = ""

    # Logging
    log_level: str = "INFO"
    log_file: str = "./logs/agent.log"
    log_max_bytes: int = 5_242_880
    log_backup_count: int = 3

    # Reports
    report_output_dir: str = "./reports"

    @property
    def target_cities_list(self) -> list[str]:
        return [c.strip() for c in self.target_cities.split(",")]

    @property
    def target_industries_list(self) -> list[str]:
        return [i.strip() for i in self.target_industries.split(",")]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _lazy_settings():
    """Proxy that defers instantiation until first attribute access."""

    class _Proxy:
        __slots__ = ()

        def __getattr__(self, name: str):
            return getattr(get_settings(), name)

    return _Proxy()


settings = _lazy_settings()


def get_profile_overrides(profile: dict | None) -> dict:
    """Merge a Profile's overrides on top of global Settings defaults.

    Returns a dict with keys: target_cities_list, target_industries_list,
    min_employees, max_employees, search_focus_terms, scoring_rubric,
    outreach_tone, target_roles, agent_company_name, agent_description.
    """
    cfg = get_settings()
    overrides: dict = {
        "target_cities_list": cfg.target_cities_list,
        "target_industries_list": cfg.target_industries_list,
        "min_employees": cfg.min_employees,
        "max_employees": cfg.max_employees,
        "search_focus_terms": "",
        "scoring_rubric": None,
        "outreach_tone": "warm",
        "outreach_instructions": "",
        "target_roles": "",
        "agent_company_name": "Blest",
        "agent_description": "a corporate English training company in Argentina",
    }

    if not profile:
        return overrides

    if profile.get("target_cities"):
        overrides["target_cities_list"] = [c.strip() for c in profile["target_cities"].split(",")]
    if profile.get("target_industries"):
        overrides["target_industries_list"] = [i.strip() for i in profile["target_industries"].split(",")]
    if profile.get("min_employees"):
        overrides["min_employees"] = profile["min_employees"]
    if profile.get("max_employees"):
        overrides["max_employees"] = profile["max_employees"]
    if profile.get("search_focus_terms"):
        overrides["search_focus_terms"] = profile["search_focus_terms"]
    if profile.get("scoring_rubric"):
        overrides["scoring_rubric"] = profile["scoring_rubric"]
    if profile.get("outreach_tone"):
        overrides["outreach_tone"] = profile["outreach_tone"]
    if profile.get("outreach_instructions"):
        overrides["outreach_instructions"] = profile["outreach_instructions"]
    if profile.get("target_roles"):
        overrides["target_roles"] = profile["target_roles"]
    if profile.get("agent_company_name"):
        overrides["agent_company_name"] = profile["agent_company_name"]
    if profile.get("agent_description"):
        overrides["agent_description"] = profile["agent_description"]

    return overrides
