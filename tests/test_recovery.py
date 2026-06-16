"""Tests for the bounced-email recovery flow (src/tools/recovery.py).

Uses in-memory SQLite (JSONB→JSON shim from conftest.py)."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Company, Contact
from src.enrichment.pipeline import EnrichmentResult
import src.tools.recovery as rec


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@contextmanager
def _fake_get_session(s):
    yield s
    s.commit()


def _seed(session, **kw):
    co = Company(id=1, name="Acme SA", domain="acme.com")
    ct = Contact(
        id=1, company_id=1, name="Juan Perez", role="HR",
        email=kw.get("email", "juan.perez@acme.com"),
        email_status=kw.get("email_status", "bounced"),
        email_source="pattern_unverified",
        enriched_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2),
        enrichment_log=kw.get("log", {"attempts": 1}),
    )
    session.add_all([co, ct])
    session.commit()
    return co, ct


class TestSelect:
    def test_only_named_bounced(self, session):
        _seed(session)  # bounced named → included
        session.add(Contact(id=2, company_id=1, name="No Email", email=None,
                            email_status="not_found"))
        session.add(Contact(id=3, company_id=1, name=None, email="x@acme.com",
                            email_status="bounced"))  # no name → excluded
        session.commit()
        rows = rec.select_bounced_contacts(session, limit=50)
        assert [c.id for c in rows] == [1]


class TestRecoverContact:
    def test_blocklists_and_clears_then_reenriches(self, session):
        _seed(session, email="juan.perez@acme.com")

        captured = {}

        def fake_enrich(cid):
            # Inspect DB state at the moment enrich_contact is invoked
            c = session.get(Contact, cid)
            captured["email_at_call"] = c.email
            captured["bad_at_call"] = list(c.enrichment_log.get("bad_emails", []))
            return EnrichmentResult(contact_id=cid, email="jperez@acme.com",
                                    email_status="verified", email_source="pattern_verified")

        with patch.object(rec, "get_session", lambda: _fake_get_session(session)), \
             patch.object(rec, "enrich_contact", side_effect=fake_enrich):
            res = rec.recover_contact(1)

        assert res.email_status == "verified"
        assert captured["email_at_call"] is None                       # cleared before re-enrich
        assert "juan.perez@acme.com" in captured["bad_at_call"]        # old address blocklisted

    def test_accumulates_bad_emails(self, session):
        _seed(session, email="second@acme.com",
              log={"attempts": 2, "bad_emails": ["first@acme.com"]})

        seen = {}

        def fake_enrich(cid):
            seen["bad"] = sorted(session.get(Contact, cid).enrichment_log["bad_emails"])
            return EnrichmentResult(contact_id=cid, email_status="not_found")

        with patch.object(rec, "get_session", lambda: _fake_get_session(session)), \
             patch.object(rec, "enrich_contact", side_effect=fake_enrich):
            rec.recover_contact(1)

        assert seen["bad"] == ["first@acme.com", "second@acme.com"]


class TestRunRecovery:
    def test_counts_recovered(self, session):
        _seed(session)
        session.add(Contact(id=2, company_id=1, name="Ana Lopez", email="a@acme.com",
                            email_status="bounced", enrichment_log={"attempts": 1}))
        session.commit()

        def fake_recover(cid):
            if cid == 1:
                return EnrichmentResult(contact_id=cid, email="ok@acme.com", email_status="verified")
            return EnrichmentResult(contact_id=cid, email_status="not_found")

        with patch.object(rec, "get_session", lambda: _fake_get_session(session)), \
             patch.object(rec, "recover_contact", side_effect=fake_recover):
            res = rec.run_recovery(limit=10, delay=0)

        assert res["processed"] == 2
        assert res["recovered"] == 1
        assert res["still_bad"] == 1

    def test_nothing_to_do(self, session):
        # no bounced contacts
        Company.__table__  # noqa
        with patch.object(rec, "get_session", lambda: _fake_get_session(session)):
            res = rec.run_recovery(limit=10, delay=0)
        assert res == {"processed": 0, "recovered": 0, "still_bad": 0}
