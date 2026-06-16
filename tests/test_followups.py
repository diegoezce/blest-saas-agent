"""Tests for the follow-up agent (src/tools/followups.py + scan_inbox_senders).

Uses an in-memory SQLite DB. The models declare JSONB columns (Postgres), so we
register a SQLite compiler that maps JSONB → JSON for DDL — DB-agnostic test setup
without needing a real Postgres.
"""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import (  # noqa: E402
    Base, Company, Contact, Opportunity, DiscoveryRun, Profile, ContactStatus,
)
import src.tools.followups as fu  # noqa: E402
from src.prompts.followup import build_followup_prompt  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _naive_days_ago(days: int) -> datetime:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)


def _seed_pushed_lead(session, *, pushed_days_ago=5, followup_count=0,
                      last_followup_days_ago=None, email_status="verified"):
    """Create a profile/run/company/contact/opportunity that has been pushed."""
    p = Profile(id=1, name="Blest Learning", agent_company_name="Blest",
                agent_description="corp English training", outreach_language="es",
                outreach_instructions="ofrecemos inglés de negocios")
    run = DiscoveryRun(id=1, profile_id=1, run_date=datetime.now().date(),
                       started_at=datetime.now())
    co = Company(id=1, name="Acme SA", domain="acme.com", description="fintech",
                 website_url="https://acme.com")
    ct = Contact(id=1, company_id=1, name="Juan Perez", role="HR Manager",
                 email="juan@acme.com", email_status=email_status, confidence_score=0.9)
    opp = Opportunity(
        id=1, run_id=1, company_id=1, score=80,
        outreach_draft="Hola Juan, te escribo por...", outreach_subject="Inglés para Acme",
        zoho_pushed_at=_naive_days_ago(pushed_days_ago),
        followup_count=followup_count,
        last_followup_at=(_naive_days_ago(last_followup_days_ago)
                          if last_followup_days_ago is not None else None),
    )
    session.add_all([p, run, co, ct, opp])
    session.commit()
    return p, run, co, ct, opp


@contextmanager
def _fake_get_session(s):
    yield s
    s.commit()


# ── scan_inbox_senders (Zoho parsing) ──────────────────────────────────────────

class TestScanInboxSenders:
    def _resp(self, payload):
        m = MagicMock(status_code=200, json=lambda: payload)
        m.raise_for_status = lambda: None
        return m

    @patch("src.integrations.zoho_mail.requests.get")
    @patch("src.integrations.zoho_mail._load_tokens")
    @patch("src.integrations.zoho_mail._get_access_token")
    def test_extracts_filters_and_keeps_latest(self, mock_tok, mock_load, mock_get):
        mock_tok.return_value = "access-token"
        mock_load.return_value = {"account_id": "1", "from_address": "me@blest.com"}
        folders = self._resp({"data": [{"folderName": "Inbox", "folderId": "999"}]})
        messages = self._resp({"data": [
            {"fromAddress": "Juan Perez <juan@acme.com>", "receivedTime": "1000"},
            {"fromAddress": "mailer-daemon@blest.com", "receivedTime": "1500"},   # noise
            {"fromAddress": "boss@blest.com", "receivedTime": "1600"},            # own domain
            {"fromAddress": "juan@acme.com", "receivedTime": "2000"},             # newer dup
            {"sender": "maria@othercorp.com", "receivedTime": "3000"},            # 'sender' field
        ]})
        mock_get.side_effect = [folders, messages]

        from src.integrations.zoho_mail import scan_inbox_senders
        res = scan_inbox_senders(max_messages=50)

        assert res["checked"] == 5
        senders = res["senders"]
        assert senders["juan@acme.com"] == 2000          # kept the latest timestamp
        assert senders["maria@othercorp.com"] == 3000
        assert "boss@blest.com" not in senders            # own domain filtered
        assert all("mailer-daemon" not in a for a in senders)

    @patch("src.integrations.zoho_mail.requests.get")
    @patch("src.integrations.zoho_mail._load_tokens")
    @patch("src.integrations.zoho_mail._get_access_token")
    def test_no_inbox_folder_returns_empty(self, mock_tok, mock_load, mock_get):
        mock_tok.return_value = "t"
        mock_load.return_value = {"account_id": "1", "from_address": "me@blest.com"}
        mock_get.return_value = self._resp({"data": [{"folderName": "Sent", "folderId": "1"}]})

        from src.integrations.zoho_mail import scan_inbox_senders
        res = scan_inbox_senders()
        assert res == {"checked": 0, "senders": {}}


# ── detect_replies ──────────────────────────────────────────────────────────────

class TestDetectReplies:
    def test_marks_reply_after_push_and_sets_status(self, session):
        _seed_pushed_lead(session, pushed_days_ago=5)
        reply_ms = int(datetime.now(timezone.utc).timestamp() * 1000)  # now (after push)

        with patch.object(fu, "scan_inbox_senders",
                          return_value={"checked": 10, "senders": {"juan@acme.com": reply_ms}}), \
             patch.object(fu, "get_session", lambda: _fake_get_session(session)):
            res = fu.detect_replies()

        assert res["newly_marked"] == 1
        assert res["matched"] == 1
        ct = session.get(Contact, 1)
        assert ct.replied_at is not None
        cs = session.query(ContactStatus).filter_by(company_id=1).first()
        assert cs is not None and cs.response_received == "replied"

    def test_ignores_mail_before_push(self, session):
        _seed_pushed_lead(session, pushed_days_ago=5)
        old_ms = int((datetime.now(timezone.utc) - timedelta(days=20)).timestamp() * 1000)

        with patch.object(fu, "scan_inbox_senders",
                          return_value={"checked": 10, "senders": {"juan@acme.com": old_ms}}), \
             patch.object(fu, "get_session", lambda: _fake_get_session(session)):
            res = fu.detect_replies()

        assert res["newly_marked"] == 0
        assert session.get(Contact, 1).replied_at is None

    def test_no_push_means_no_reply(self, session):
        # Contact exists but the opportunity was never pushed → not a reply to us.
        _seed_pushed_lead(session, pushed_days_ago=5)
        opp = session.get(Opportunity, 1)
        opp.zoho_pushed_at = None
        session.commit()
        reply_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        with patch.object(fu, "scan_inbox_senders",
                          return_value={"checked": 1, "senders": {"juan@acme.com": reply_ms}}), \
             patch.object(fu, "get_session", lambda: _fake_get_session(session)):
            res = fu.detect_replies()

        assert res["newly_marked"] == 0

    def test_does_not_overwrite_manual_response(self, session):
        _seed_pushed_lead(session, pushed_days_ago=5)
        session.add(ContactStatus(company_id=1, response_received="interested",
                                  contacted_at=_naive_days_ago(5)))
        session.commit()
        reply_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        with patch.object(fu, "scan_inbox_senders",
                          return_value={"checked": 1, "senders": {"juan@acme.com": reply_ms}}), \
             patch.object(fu, "get_session", lambda: _fake_get_session(session)):
            fu.detect_replies()

        cs = session.query(ContactStatus).filter_by(company_id=1).first()
        assert cs.response_received == "interested"   # manual feedback preserved
        assert session.get(Contact, 1).replied_at is not None


# ── select_followup_candidates (cadence) ───────────────────────────────────────

class TestCadence:
    def test_touch1_due_after_4_days(self, session):
        _seed_pushed_lead(session, pushed_days_ago=5, followup_count=0)
        cands = fu.select_followup_candidates(session)
        assert len(cands) == 1
        opp, co, ct, prof = cands[0]
        assert (opp.followup_count or 0) + 1 == 1
        assert ct.email == "juan@acme.com"

    def test_touch1_not_due_before_4_days(self, session):
        _seed_pushed_lead(session, pushed_days_ago=2, followup_count=0)
        assert fu.select_followup_candidates(session) == []

    def test_touch2_due_after_6_days_since_last(self, session):
        _seed_pushed_lead(session, pushed_days_ago=12, followup_count=1,
                          last_followup_days_ago=7)
        cands = fu.select_followup_candidates(session)
        assert len(cands) == 1
        assert (cands[0][0].followup_count or 0) + 1 == 2

    def test_touch2_not_due_too_soon(self, session):
        _seed_pushed_lead(session, pushed_days_ago=8, followup_count=1,
                          last_followup_days_ago=3)
        assert fu.select_followup_candidates(session) == []

    def test_maxed_out_excluded(self, session):
        _seed_pushed_lead(session, pushed_days_ago=30, followup_count=2,
                          last_followup_days_ago=10)
        assert fu.select_followup_candidates(session) == []

    def test_replied_excluded(self, session):
        _seed_pushed_lead(session, pushed_days_ago=5, followup_count=0)
        session.get(Contact, 1).replied_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()
        assert fu.select_followup_candidates(session) == []

    def test_manual_response_excluded(self, session):
        _seed_pushed_lead(session, pushed_days_ago=5, followup_count=0)
        session.add(ContactStatus(company_id=1, response_received="not_interested",
                                  contacted_at=_naive_days_ago(5)))
        session.commit()
        assert fu.select_followup_candidates(session) == []

    def test_no_verified_email_excluded(self, session):
        _seed_pushed_lead(session, pushed_days_ago=5, followup_count=0,
                          email_status="not_found")
        assert fu.select_followup_candidates(session) == []

    def test_never_pushed_excluded(self, session):
        _seed_pushed_lead(session, pushed_days_ago=5, followup_count=0)
        session.get(Opportunity, 1).zoho_pushed_at = None
        session.commit()
        assert fu.select_followup_candidates(session) == []


# ── generate_followup (subject prefixing) ───────────────────────────────────────

class TestGenerateFollowup:
    def _mock_instructor(self, body="Hola Juan, te escribo de nuevo. ¿Tenés 15 minutos?"):
        client = MagicMock()
        client.messages.create.return_value = MagicMock(body=body)
        return client

    def test_adds_re_prefix(self, session):
        _, _, co, ct, opp = _seed_pushed_lead(session)
        with patch("instructor.from_anthropic", return_value=self._mock_instructor()), \
             patch("anthropic.Anthropic", return_value=MagicMock()):
            subject, body = fu.generate_followup(co, ct, opp, session.get(Profile, 1))
        assert subject == "Re: Inglés para Acme"
        assert body.startswith("Hola Juan")

    def test_does_not_double_prefix(self, session):
        _, _, co, ct, opp = _seed_pushed_lead(session)
        opp.outreach_subject = "Re: ya tiene prefijo"
        session.commit()
        with patch("instructor.from_anthropic", return_value=self._mock_instructor()), \
             patch("anthropic.Anthropic", return_value=MagicMock()):
            subject, _ = fu.generate_followup(co, ct, opp, session.get(Profile, 1))
        assert subject == "Re: ya tiene prefijo"


# ── run_followups (orchestration) ───────────────────────────────────────────────

class TestRunFollowups:
    def test_pushes_and_bumps_counters(self, session):
        _seed_pushed_lead(session, pushed_days_ago=5, followup_count=0)

        with patch.object(fu, "detect_replies", return_value={"newly_marked": 0}), \
             patch.object(fu, "generate_followup", return_value=("Re: Inglés para Acme", "cuerpo")), \
             patch.object(fu, "zoho_create_draft", return_value={"status": "ok"}) as mock_draft:
            res = fu.run_followups(session, batch=15, delay=0)

        assert res["drafted"] == 1
        assert res["candidates"] == 1
        mock_draft.assert_called_once()
        opp = session.get(Opportunity, 1)
        assert opp.followup_count == 1
        assert opp.last_followup_at is not None
        assert opp.followup_subject == "Re: Inglés para Acme"
        assert opp.followup_draft == "cuerpo"

    def test_nothing_due_pushes_nothing(self, session):
        _seed_pushed_lead(session, pushed_days_ago=1, followup_count=0)  # too recent
        with patch.object(fu, "detect_replies", return_value={"newly_marked": 0}), \
             patch.object(fu, "generate_followup") as mock_gen, \
             patch.object(fu, "zoho_create_draft") as mock_draft:
            res = fu.run_followups(session, batch=15, delay=0)
        assert res["drafted"] == 0
        mock_gen.assert_not_called()
        mock_draft.assert_not_called()

    def test_draft_failure_does_not_bump(self, session):
        _seed_pushed_lead(session, pushed_days_ago=5, followup_count=0)
        with patch.object(fu, "detect_replies", return_value={"newly_marked": 0}), \
             patch.object(fu, "generate_followup", return_value=("Re: x", "body")), \
             patch.object(fu, "zoho_create_draft", side_effect=RuntimeError("zoho down")):
            res = fu.run_followups(session, batch=15, delay=0)
        assert res["drafted"] == 0
        assert session.get(Opportunity, 1).followup_count == 0


# ── build_followup_prompt (language) ────────────────────────────────────────────

class TestPrompt:
    def _build(self, language):
        return build_followup_prompt(
            agent_name="Blest", agent_description="corp English training",
            outreach_instructions_block="", original_email="Hola Juan...",
            days_since_contact=5, company_context_json="{}", followup_number=1,
            outreach_language=language,
        )

    def test_spanish_uses_voseo(self):
        s = self._build("es")
        assert "voseo" in s
        assert "50–120" in s

    def test_english_directives(self):
        s = self._build("en")
        assert "professional English" in s

    def test_includes_original_and_followup_number(self):
        s = self._build("es")
        assert "Hola Juan..." in s
        assert "follow-up #1 of 2" in s
