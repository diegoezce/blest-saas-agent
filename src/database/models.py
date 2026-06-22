from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Float, Boolean,
    ForeignKey, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False, unique=True)
    description = Column(Text, nullable=True)
    active = Column(Boolean, default=True)

    # Who is selling
    agent_company_name = Column(Text, nullable=False, comment="e.g. Blest")
    agent_description = Column(Text, nullable=False, comment="What the agent does/sells, for prompts")

    # Who to find (target market)
    target_industries = Column(Text, nullable=True, comment="Comma-separated; overrides global config")
    target_cities = Column(Text, nullable=True, comment="Comma-separated; overrides global config")
    min_employees = Column(Integer, nullable=True)
    max_employees = Column(Integer, nullable=True)
    search_focus_terms = Column(Text, nullable=True, comment="Extra context for query generation")

    # How to score
    scoring_rubric = Column(JSONB, nullable=True, comment="Custom scoring rubric JSON")
    outreach_tone = Column(Text, nullable=True, comment="e.g. warm, direct, referral")
    outreach_language = Column(Text, nullable=True, comment="Outreach email language: 'es' or 'en' (default es)")
    outreach_instructions = Column(
        Text, nullable=True,
        comment="Custom outreach guidance: value props, proof points, what to emphasize/avoid",
    )

    # Contact targeting
    target_roles = Column(Text, nullable=True, comment="Comma-separated priority role list")

    created_at = Column(DateTime, server_default=func.now())

    runs = relationship("DiscoveryRun", back_populates="profile")


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=True)
    run_date = Column(Date, nullable=False)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="running")
    companies_found = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    search_queries_used = Column(JSONB, nullable=True)
    config_snapshot = Column(JSONB, nullable=True)
    enriched_contact_ids = Column(JSONB, nullable=True, comment="Quick Run: contact IDs that were enriched in this run")
    created_at = Column(DateTime, server_default=func.now())

    profile = relationship("Profile", back_populates="runs")
    opportunities = relationship("Opportunity", back_populates="run", cascade="all, delete-orphan")
    reports = relationship("DailyReport", back_populates="run", cascade="all, delete-orphan")


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    domain = Column(Text, unique=True, nullable=True)
    industry = Column(Text, nullable=True)
    size_estimate = Column(Text, nullable=True)
    location = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    website_url = Column(Text, nullable=True)
    linkedin_url = Column(Text, nullable=True)
    source = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    raw_data = Column(JSONB, nullable=True)
    first_seen_at = Column(DateTime, server_default=func.now())
    last_updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    opportunities = relationship("Opportunity", back_populates="company")
    contacts = relationship("Contact", back_populates="company", cascade="all, delete-orphan")
    contact_status = relationship("ContactStatus", back_populates="company", uselist=False, cascade="all, delete-orphan")


class ContactStatus(Base):
    __tablename__ = "contact_status"

    company_id = Column(Integer, ForeignKey("companies.id"), primary_key=True)
    contacted_at = Column(DateTime, nullable=False, default=func.now())
    comment = Column(Text, nullable=True)
    contact_method = Column(String(50), nullable=True)
    response_received = Column(String(30), nullable=True)
    follow_up_date = Column(Date, nullable=True)
    icp_feedback = Column(JSONB, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="contact_status")


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (UniqueConstraint("run_id", "company_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("discovery_runs.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    score = Column(Integer, nullable=False)
    score_breakdown = Column(JSONB, nullable=True)
    score_explanation = Column(Text, nullable=True)
    status = Column(String(20), default="new")
    priority = Column(String(20), nullable=True)
    insights = Column(Text, nullable=True)
    evidence = Column(JSONB, nullable=True)
    suggested_approach = Column(Text, nullable=True)
    conversation_angle = Column(Text, nullable=True)
    outreach_draft = Column(Text, nullable=True)
    outreach_subject = Column(Text, nullable=True)
    zoho_pushed_at = Column(DateTime, nullable=True)
    # Follow-up tracking (cadence: touch #1 ~day 4, touch #2 ~day 10)
    followup_count = Column(Integer, server_default="0")
    last_followup_at = Column(DateTime, nullable=True)
    followup_subject = Column(Text, nullable=True)
    followup_draft = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    run = relationship("DiscoveryRun", back_populates="opportunities")
    company = relationship("Company", back_populates="opportunities")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(Text, nullable=True)
    role = Column(Text, nullable=True)
    role_category = Column(Text, nullable=True)
    linkedin_url = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)
    source = Column(Text, nullable=True)
    raw_data = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # Enrichment fields
    email_status = Column(String(20), nullable=True)   # verified | probable | catch_all | not_found
    email_source = Column(String(30), nullable=True)   # site_scrape | pattern_verified | hunter
    phone_whatsapp = Column(Text, nullable=True)
    enriched_at = Column(DateTime, nullable=True)
    enrichment_log = Column(JSONB, nullable=True)
    replied_at = Column(DateTime, nullable=True)   # set when a reply from this email is seen in the Zoho inbox
    is_primary = Column(Boolean, nullable=True, default=False)

    company = relationship("Company", back_populates="contacts")


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("discovery_runs.id"), nullable=False)
    report_date = Column(Date, nullable=False)
    report_json = Column(JSONB, nullable=False)
    report_markdown = Column(Text, nullable=True)
    top_opportunities = Column(JSONB, nullable=True)
    quick_wins = Column(JSONB, nullable=True)
    strategic_opportunities = Column(JSONB, nullable=True)
    follow_up_suggestions = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    run = relationship("DiscoveryRun", back_populates="reports")

