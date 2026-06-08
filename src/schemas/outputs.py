from typing import Literal, Optional
from pydantic import BaseModel, Field


class SearchQueryList(BaseModel):
    queries: list[str] = Field(description="List of search queries to execute")


class CompanyDiscovery(BaseModel):
    name: str
    website_url: Optional[str] = None
    domain: Optional[str] = None
    linkedin_url: Optional[str] = None
    industry: str = "unknown"
    size_estimate: str = "unknown"
    location: str = "Argentina"
    description: str
    remote_friendly: bool = False
    has_international_clients: bool = False
    has_english_job_postings: bool = False
    source: str = "tavily"
    source_url: Optional[str] = None
    signals: list[str] = Field(default_factory=list)


class CompanyList(BaseModel):
    companies: list[CompanyDiscovery] = Field(description="List of discovered companies")


class ScoringFactors(BaseModel):
    tamaño_instituto: int = Field(ge=0, le=20)
    señales_crecimiento: int = Field(ge=0, le=25)
    dolor_admin_visible: int = Field(ge=0, le=20)
    adopcion_tecnologica: int = Field(ge=0, le=15)
    reputacion_establecida: int = Field(ge=0, le=10)
    señales_inversion: int = Field(ge=0, le=10)


class ScoredCompany(BaseModel):
    company_name: str
    score: int = Field(ge=1, le=100)
    score_explanation: str
    factors: ScoringFactors
    priority: Literal["quick_win", "strategic", "low_priority"]


class ScoredCompanyList(BaseModel):
    companies: list[ScoredCompany] = Field(description="List of scored companies")


class ContactPerson(BaseModel):
    name: Optional[str] = None
    role: str
    role_category: Literal["founder", "director", "academic", "admin", "other"]
    linkedin_url: Optional[str] = None
    email: Optional[str] = None
    confidence: Literal["high", "medium", "low"] = "low"
    notes: str = ""


class CompanyContacts(BaseModel):
    company_name: str
    contacts: list[ContactPerson]


class CompanyInsight(BaseModel):
    company_name: str
    why_they_need_training: str
    evidence_found: list[str]
    suggested_approach: str
    conversation_starter: str


class CompanyInsightList(BaseModel):
    insights: list[CompanyInsight]


class OutreachDraft(BaseModel):
    company_name: str
    contact_name: Optional[str] = None
    subject_line: str
    body: str
    channel: Literal["email", "linkedin"]
    language: Literal["en", "es"] = "en"
    tone: Literal["warm", "direct", "referral"]


class CompanyOutreach(BaseModel):
    drafts: list[OutreachDraft] = Field(description="One draft per channel (email + linkedin)")


class DailyReport(BaseModel):
    run_date: str
    run_id: int
    total_companies_found: int
    quick_wins: list[ScoredCompany]
    strategic_opportunities: list[ScoredCompany]
    top_contacts: list[ContactPerson]
    top_insights: list[CompanyInsight]
    outreach_drafts: list[OutreachDraft]
    follow_up_suggestions: list[str]
