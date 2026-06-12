import pytest
from unittest.mock import patch, MagicMock
from src.enrichment.scraper import scrape_domain, _can_fetch, _EMAIL_RE, _PHONE_RE


FIXTURE_HTML = """
<html><body>
<p>Contactanos en info@empresa.com o ventas@empresa.com</p>
<p>También por mail a carlos.garcia@empresa.com</p>
<p>WhatsApp: +54 9 11 1234-5678</p>
<p>Tel: 011-4567-8901</p>
</body></html>
"""


class TestEmailRegex:
    def test_finds_simple_email(self):
        assert "user@example.com" in _EMAIL_RE.findall("Contact user@example.com today")

    def test_finds_multiple_emails(self):
        matches = _EMAIL_RE.findall("a@b.com and c@d.org")
        assert len(matches) == 2

    def test_ignores_invalid(self):
        matches = _EMAIL_RE.findall("notanemail @broken no@")
        assert not any("@broken" in m for m in matches)


class TestPhoneRegex:
    def test_finds_whatsapp_format(self):
        matches = _PHONE_RE.findall("+54 9 11 1234-5678")
        assert len(matches) >= 1

    def test_finds_landline(self):
        matches = _PHONE_RE.findall("011-4567-8901")
        assert len(matches) >= 1


class TestScrapeDomain:
    @patch("src.enrichment.scraper._can_fetch", return_value=True)
    @patch("src.enrichment.scraper._get_page")
    @patch("time.sleep")
    def test_extracts_emails_from_html(self, mock_sleep, mock_get_page, mock_robots):
        mock_get_page.return_value = FIXTURE_HTML
        result = scrape_domain("empresa.com")
        assert "info@empresa.com" in result.emails
        assert "carlos.garcia@empresa.com" in result.emails

    @patch("src.enrichment.scraper._can_fetch", return_value=True)
    @patch("src.enrichment.scraper._get_page")
    @patch("time.sleep")
    def test_extracts_phones(self, mock_sleep, mock_get_page, mock_robots):
        mock_get_page.return_value = FIXTURE_HTML
        result = scrape_domain("empresa.com")
        assert len(result.phones) >= 1

    @patch("src.enrichment.scraper._can_fetch", return_value=True)
    @patch("src.enrichment.scraper._get_page", return_value=None)
    @patch("time.sleep")
    def test_handles_all_pages_unreachable(self, mock_sleep, mock_get_page, mock_robots):
        result = scrape_domain("unreachable.com")
        assert result.emails == []
        assert result.phones == []
        assert result.pages_checked == 0

    @patch("src.enrichment.scraper._can_fetch", return_value=False)
    @patch("time.sleep")
    def test_respects_robots_txt(self, mock_sleep, mock_robots):
        result = scrape_domain("blocked.com")
        assert result.blocked_by_robots is True
        assert result.emails == []

    @patch("src.enrichment.scraper._can_fetch", return_value=True)
    @patch("src.enrichment.scraper._get_page")
    @patch("time.sleep")
    def test_max_pages_limit(self, mock_sleep, mock_get_page, mock_robots):
        mock_get_page.return_value = "<html><body>no emails here</body></html>"
        result = scrape_domain("empresa.com")
        assert result.pages_checked <= 6

    def test_empty_domain_returns_error(self):
        result = scrape_domain("")
        assert result.error == "empty domain"

    @patch("src.enrichment.scraper._can_fetch", return_value=True)
    @patch("src.enrichment.scraper._get_page")
    @patch("time.sleep")
    def test_deduplicates_emails(self, mock_sleep, mock_get_page, mock_robots):
        html = "<html><body>info@empresa.com info@empresa.com</body></html>"
        mock_get_page.return_value = html
        result = scrape_domain("empresa.com")
        assert result.emails.count("info@empresa.com") == 1
