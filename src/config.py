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
    scheduler_timezone: str = "America/Argentina/Buenos_Aires"

    # Workflow tuning
    discovery_queries_per_run: int = 8
    max_companies_to_score: int = 30
    max_companies_for_contacts: int = 20
    max_companies_for_insights: int = 10
    max_companies_for_outreach: int = 5

    # Business targeting
    target_cities: str = "Buenos Aires,Córdoba,Rosario,Mendoza"
    target_industries: str = "technology,consulting,accounting,professional_services,fintech,legaltech"
    min_employees: int = 20
    max_employees: int = 500

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


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
