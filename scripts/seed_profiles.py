"""
Seed script to create the initial Profile records.

Usage:
  python scripts/seed_profiles.py

Creates the two base profiles:
  1. "Blest Learning" — corporate English training for mid-large companies
  2. "Blest App" — SaaS platform for English academies and language institutes
"""

import sys
import pathlib

# Add project root to path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.database.session import get_session, init_db
from src.database.models import Profile


PROFILES = [
    {
        "name": "Blest Learning",
        "description": "Corporate English training for Argentine mid-to-large companies in tech, consulting, fintech, oil & gas and other industries.",
        "active": True,
        "agent_company_name": "Blest",
        "agent_description": "a corporate English training provider in Argentina",
        "target_industries": "technology,consulting,fintech,legaltech,accounting,professional_services,oil_gas,energy",
        "target_cities": "Buenos Aires,Córdoba,Rosario,Mendoza,Neuquén",
        "min_employees": 20,
        "max_employees": 500,
        "search_focus_terms": "improve their team's business English: written correspondence, client calls, presentations, async collaboration with international teams",
        "scoring_rubric": None,  # Uses DEFAULT_SCORING_RUBRIC from prompts/scoring.py
        "outreach_tone": "warm",
        "target_roles": "Learning & Development (L&D) Manager / Talent Development / Capacitación,\nHR Manager / Gerente de Recursos Humanos / People Manager,\nChief People Officer / VP People / Head of Talent,\nOperations Manager (for companies < 50 employees),\nFounder / CEO / Managing Director (for companies < 50 employees)",
    },
    {
        "name": "Blest App",
        "description": "Blest App is a SaaS platform for English academies and language institutes to manage their operations, students, billing, and teacher coordination.",
        "active": True,
        "agent_company_name": "Blest",
        "agent_description": "a SaaS platform for English academies and language institutes to manage their operations, students, billing, and teacher coordination",
        "target_industries": "education,language_teaching,english_institutes,training_centers,academias_de_ingles,institutos_de_idiomas",
        "target_cities": "Buenos Aires,Córdoba,Rosario,Mendoza,Neuquén,La Plata,Mar del Plata,Salta,Tucumán,Santa Fe",
        "min_employees": 2,
        "max_employees": 30,
        "search_focus_terms": "help English academies and language institutes streamline their operations: manage student enrollment, scheduling, billing, teacher coordination, progress tracking, and multilevel group classes",
        "scoring_rubric": None,
        "outreach_tone": "professional",
        "target_roles": "Director / Owner / Founder of English Academy or Language Institute,\nAcademic Director / Coordinador Académico de Instituto de Inglés,\nAdministrative Manager / Administrador de Instituto de Idiomas,\nHead of Studies / Jefe de Estudios de Academia de Inglés,\nOperations Manager / Gerente Operativo de Instituto de Idiomas",
    },
]


def seed():
    init_db()

    with get_session() as session:
        existing = session.query(Profile).count()
        if existing > 0:
            print(f"⚠️  Database already has {existing} profile(s). Skipping seed to avoid duplicates.")
            print("   Use --force to recreate.")
            return

        for data in PROFILES:
            profile = Profile(**data)
            session.add(profile)

    print(f"✅ Seeded {len(PROFILES)} profile(s):")
    for p in PROFILES:
        print(f"   • {p['name']}")


if __name__ == "__main__":
    seed()
