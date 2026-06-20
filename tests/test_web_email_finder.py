import pytest
from src.enrichment.web_email_finder import (
    _extract_emails_from_text,
    _name_matches_local,
    _is_generic_inbox,
    _host_blocked,
)


class TestExtractEmailsFromText:
    def test_single_email(self):
        text = "Contact us at info@acme.com for more info"
        emails = _extract_emails_from_text(text)
        assert "info@acme.com" in emails

    def test_multiple_emails(self):
        text = "Email carlos@acme.com or juan@acme.com"
        emails = _extract_emails_from_text(text)
        assert "carlos@acme.com" in emails
        assert "juan@acme.com" in emails

    def test_email_in_title(self):
        text = "Contact: carlos.perez@acme.com.ar"
        emails = _extract_emails_from_text(text)
        assert "carlos.perez@acme.com.ar" in emails

    def test_no_emails(self):
        text = "No email here, just plain text"
        emails = _extract_emails_from_text(text)
        assert len(emails) == 0

    def test_malformed_email(self):
        text = "Invalid: user@@ or @domain.com"
        emails = _extract_emails_from_text(text)
        # Regex should not match these
        assert len(emails) == 0


class TestNameMatchesLocal:
    def test_first_name_match(self):
        assert _name_matches_local("Carlos", "Perez", "carlos.perez") is True

    def test_last_name_match(self):
        assert _name_matches_local("Carlos", "Perez", "perez.carlos") is True

    def test_first_name_only(self):
        assert _name_matches_local("Carlos", "", "carlos") is True

    def test_no_match(self):
        assert _name_matches_local("Carlos", "Perez", "juan.garcia") is False

    def test_partial_match_rejected(self):
        # "car" is not a full name match — must contain "carlos"
        assert _name_matches_local("Carlos", "Perez", "car.perez") is False

    def test_case_insensitive(self):
        assert _name_matches_local("CARLOS", "perez", "carlos.perez") is True

    def test_empty_names(self):
        assert _name_matches_local("", "", "carlos.perez") is False


class TestIsGenericInbox:
    def test_generic_contacto(self):
        assert _is_generic_inbox("contacto") is True

    def test_generic_info(self):
        assert _is_generic_inbox("info") is True

    def test_generic_sales(self):
        assert _is_generic_inbox("ventas") is True

    def test_named_email(self):
        assert _is_generic_inbox("carlos.perez") is False

    def test_case_insensitive(self):
        assert _is_generic_inbox("CONTACTO") is True

    def test_prefix_match(self):
        assert _is_generic_inbox("contacto-arg") is True


class TestHostBlocked:
    def test_linkedin_blocked(self):
        assert _host_blocked("linkedin.com") is True

    def test_indeed_blocked(self):
        assert _host_blocked("indeed.com") is True

    def test_subdomain_of_blocked(self):
        assert _host_blocked("careers.linkedin.com") is True

    def test_company_domain_allowed(self):
        assert _host_blocked("acme.com") is False

    def test_company_ar_domain_allowed(self):
        assert _host_blocked("acme.com.ar") is False

    def test_glassdoor_ar_blocked(self):
        assert _host_blocked("glassdoor.com.ar") is True
