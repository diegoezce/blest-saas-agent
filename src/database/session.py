import logging
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def _normalize_db_url(url: str) -> str:
    """Rewrite Railway's postgres:// URL to the psycopg2 dialect SQLAlchemy expects."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def get_engine():
    global _engine
    if _engine is None:
        from src.config import settings
        url = _normalize_db_url(settings.database_url)
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal


@contextmanager
def get_session() -> Session:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _seed_default_profiles() -> None:
    """Auto-seed default profiles if the profiles table is empty."""
    from src.database.models import Profile
    try:
        with get_session() as session:
            existing = session.query(Profile).count()
            if existing > 0:
                return

            profiles = [
                Profile(
                    name="Blest Learning",
                    description="Corporate English training for Argentine mid-to-large companies in tech, consulting, fintech, oil & gas and other industries.",
                    active=True,
                    agent_company_name="Blest",
                    agent_description="a corporate English training provider in Argentina",
                    target_industries="technology,consulting,fintech,legaltech,accounting,professional_services,oil_gas,energy",
                    target_cities="Buenos Aires,Córdoba,Rosario,Mendoza,Neuquén",
                    min_employees=20,
                    max_employees=500,
                    search_focus_terms="improve their team's business English: written correspondence, client calls, presentations, async collaboration with international teams",
                    outreach_tone="warm",
                    outreach_language="es",
                    target_roles="Learning & Development (L&D) Manager / Talent Development / Capacitación,\nHR Manager / Gerente de Recursos Humanos / People Manager,\nChief People Officer / VP People / Head of Talent,\nOperations Manager (for companies < 50 employees),\nFounder / CEO / Managing Director (for companies < 50 employees)",
                ),
                Profile(
                    name="Blest App",
                    description="Blest App is a SaaS platform for English academies and language institutes to manage their operations, students, billing, and teacher coordination.",
                    active=True,
                    agent_company_name="Blest",
                    agent_description="a SaaS platform for English academies and language institutes to manage their operations, students, billing, and teacher coordination",
                    target_industries="education,language_teaching,english_institutes,training_centers,academias_de_ingles,institutos_de_idiomas",
                    target_cities="Buenos Aires,Córdoba,Rosario,Mendoza,Neuquén,La Plata,Mar del Plata,Salta,Tucumán,Santa Fe",
                    min_employees=2,
                    max_employees=30,
                    search_focus_terms="help English academies and language institutes streamline their operations: manage student enrollment, scheduling, billing, teacher coordination, progress tracking, and multilevel group classes",
                    outreach_tone="professional",
                    outreach_language="es",
                    target_roles="Director / Owner / Founder of English Academy or Language Institute,\nAcademic Director / Coordinador Académico de Instituto de Inglés,\nAdministrative Manager / Administrador de Instituto de Idiomas,\nHead of Studies / Jefe de Estudios de Academia de Inglés,\nOperations Manager / Gerente Operativo de Instituto de Idiomas",
                ),
            ]
            for p in profiles:
                session.add(p)
            logger.info(f"Auto-seeded {len(profiles)} default profiles")
    except Exception as e:
        logger.warning(f"Could not auto-seed profiles: {e}")


def init_db() -> None:
    from src.database.models import Base
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=get_engine())
    logger.info("Database tables ready.")

    # Run migrations for columns added after initial creation
    _run_migrations()

    _seed_default_profiles()


def _run_migrations() -> None:
    """Apply any ALTER TABLE migrations needed for existing databases."""
    from sqlalchemy import inspect, text
    try:
        engine = get_engine()
        inspector = inspect(engine)
        discovery_cols = [c["name"] for c in inspector.get_columns("discovery_runs")]
        with engine.connect() as conn:
            if "profile_id" not in discovery_cols:
                conn.execute(text(
                    "ALTER TABLE discovery_runs ADD COLUMN profile_id INTEGER REFERENCES profiles(id)"
                ))
                conn.commit()
                logger.info("Migration: added profile_id column to discovery_runs")
    except Exception as e:
        logger.info(f"Migration note (non-fatal): {e}")

    # Profile outreach_instructions column
    try:
        engine = get_engine()
        inspector = inspect(engine)
        profile_cols = {c["name"] for c in inspector.get_columns("profiles")}
        if "outreach_instructions" not in profile_cols:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS outreach_instructions TEXT"
                ))
                conn.commit()
                logger.info("Migration: added profiles.outreach_instructions")
        if "outreach_language" not in profile_cols:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS outreach_language TEXT"
                ))
                conn.commit()
                logger.info("Migration: added profiles.outreach_language")
        if "is_default" not in profile_cols:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE"
                ))
                conn.commit()
                logger.info("Migration: added profiles.is_default")
    except Exception as e:
        logger.info(f"Migration note (non-fatal): {e}")

    # Opportunity tracking columns (zoho push + subject)
    try:
        engine = get_engine()
        inspector = inspect(engine)
        opp_cols = {c["name"] for c in inspector.get_columns("opportunities")}
        new_opp_cols = [
            ("outreach_subject",  "TEXT"),
            ("zoho_pushed_at",    "TIMESTAMP"),
            ("followup_count",    "INTEGER DEFAULT 0"),
            ("last_followup_at",  "TIMESTAMP"),
            ("followup_subject",  "TEXT"),
            ("followup_draft",    "TEXT"),
        ]
        with engine.connect() as conn:
            for col_name, col_type in new_opp_cols:
                if col_name not in opp_cols:
                    conn.execute(text(
                        f"ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                    ))
                    conn.commit()
                    logger.info(f"Migration: added opportunities.{col_name}")
    except Exception as e:
        logger.info(f"Migration note (non-fatal): {e}")

    # Contact enrichment columns
    try:
        engine = get_engine()
        inspector = inspect(engine)
        contact_cols = {c["name"] for c in inspector.get_columns("contacts")}
        new_cols = [
            ("email_status",   "VARCHAR(20)"),
            ("email_source",   "VARCHAR(30)"),
            ("phone_whatsapp", "TEXT"),
            ("enriched_at",    "TIMESTAMP"),
            ("enrichment_log", "JSONB"),
            ("replied_at",       "TIMESTAMP"),
            ("draft_sent_at",    "TIMESTAMP"),
            ("is_primary",       "BOOLEAN DEFAULT FALSE"),
            ("unsubscribed_at",  "TIMESTAMP"),
        ]
        with engine.connect() as conn:
            for col_name, col_type in new_cols:
                if col_name not in contact_cols:
                    conn.execute(text(
                        f"ALTER TABLE contacts ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                    ))
                    conn.commit()
                    logger.info(f"Migration: added contacts.{col_name}")
    except Exception as e:
        logger.info(f"Migration note (non-fatal): {e}")

    # Quick Run enriched_contact_ids column
    try:
        engine = get_engine()
        inspector = inspect(engine)
        discovery_cols = {c["name"] for c in inspector.get_columns("discovery_runs")}
        if "enriched_contact_ids" not in discovery_cols:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE discovery_runs ADD COLUMN IF NOT EXISTS enriched_contact_ids JSONB"
                ))
                conn.commit()
                logger.info("Migration: added discovery_runs.enriched_contact_ids")
    except Exception as e:
        logger.info(f"Migration note (non-fatal): {e}")
