"""Tests for the free local pre-filter verifier + the ChainVerifier + factory wiring."""
from unittest.mock import patch, MagicMock

import pytest

from src.enrichment.providers.base import VerifyResult
from src.enrichment.providers.local_filter import LocalFilterVerifier, ChainVerifier


class TestLocalFilter:
    def test_bad_syntax_is_invalid(self):
        assert LocalFilterVerifier().verify("not-an-email").status == "invalid"
        assert LocalFilterVerifier().verify("a@b").status == "invalid"

    def test_disposable_is_invalid(self):
        r = LocalFilterVerifier().verify("juan@mailinator.com")
        assert r.status == "invalid" and r.raw["reason"] == "disposable"

    @patch("src.enrichment.providers.local_filter._has_mail_records", return_value=False)
    def test_no_mx_is_invalid(self, _mx):
        r = LocalFilterVerifier().verify("juan@deadcorp.com")
        assert r.status == "invalid" and r.raw["reason"] == "no_mx"

    @patch("src.enrichment.providers.local_filter._has_mail_records", return_value=True)
    def test_live_domain_is_unknown_not_valid(self, _mx):
        r = LocalFilterVerifier().verify("juan@acme.com")
        assert r.status == "unknown"          # never confirms a mailbox
        assert r.raw["role"] is False

    @patch("src.enrichment.providers.local_filter._has_mail_records", return_value=True)
    def test_role_account_flagged(self, _mx):
        r = LocalFilterVerifier().verify("info@acme.com")
        assert r.status == "unknown" and r.raw["role"] is True

    @patch("src.enrichment.providers.local_filter._has_mail_records", return_value=None)
    def test_dns_failure_is_unknown(self, _mx):
        r = LocalFilterVerifier().verify("juan@acme.com")
        assert r.status == "unknown"          # transient DNS failure → don't reject


class TestChainVerifier:
    def test_invalid_short_circuits_paid(self):
        paid = MagicMock()
        pre = MagicMock()
        pre.verify.return_value = VerifyResult(status="invalid")
        chain = ChainVerifier(pre, paid)
        r = chain.verify("x@dead.com")
        assert r.status == "invalid"
        paid.verify.assert_not_called()       # saved a credit

    def test_unknown_delegates_to_paid(self):
        paid = MagicMock()
        paid.verify.return_value = VerifyResult(status="valid", confidence=1.0)
        pre = MagicMock()
        pre.verify.return_value = VerifyResult(status="unknown")
        chain = ChainVerifier(pre, paid)
        r = chain.verify("juan@acme.com")
        assert r.status == "valid"
        paid.verify.assert_called_once()


class TestFactory:
    def _get(self, monkeypatch, provider, **env):
        monkeypatch.setenv("EMAIL_VERIFIER_PROVIDER", provider)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        from src.enrichment.providers import get_verifier
        return get_verifier()

    def test_local(self, monkeypatch):
        assert type(self._get(monkeypatch, "local")).__name__ == "LocalFilterVerifier"

    def test_neverbounce(self, monkeypatch):
        assert type(self._get(monkeypatch, "neverbounce")).__name__ == "NeverBounceProvider"

    def test_millionverifier_default(self, monkeypatch):
        assert type(self._get(monkeypatch, "millionverifier")).__name__ == "MillionVerifierProvider"

    def test_smart_chain_prefers_neverbounce_when_key_set(self, monkeypatch):
        g = self._get(monkeypatch, "smart", NEVERBOUNCE_API_KEY="k")
        assert type(g).__name__ == "ChainVerifier"
        assert type(g._paid).__name__ == "NeverBounceProvider"

    def test_smart_chain_falls_back_to_mv_without_nb_key(self, monkeypatch):
        monkeypatch.delenv("NEVERBOUNCE_API_KEY", raising=False)
        monkeypatch.delenv("EMAIL_VERIFIER_BACKEND", raising=False)
        g = self._get(monkeypatch, "chain")
        assert type(g._paid).__name__ == "MillionVerifierProvider"

    def test_unknown_falls_back_to_mv(self, monkeypatch):
        assert type(self._get(monkeypatch, "bogus")).__name__ == "MillionVerifierProvider"
