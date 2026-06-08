from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Float,
    ForeignKey, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_date = Column(Date, nullable=False)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="running")
    companies_found = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    search_queries_used = Column(JSONB, nullable=True)
    config_snapshot = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    opportunities = relationship("Opportunity", back_populates="run", cascade="all, delete-orphan")
    reports = relationship("DailyReport", back_populates="run", cascade="all, delete-orphan")
    events = relationship("RunEvent", back_populates="run", cascade="all, delete-orphan")


class RunEvent(Base):
    __tablename__ = "run_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("discovery_runs.id"), nullable=False, index=True)
    level = Column(String(20), nullable=False, default="info")
    step = Column(String(50), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    run = relationship("DiscoveryRun", back_populates="events")


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
