import pytest
from unittest.mock import patch, MagicMock
from src.enrichment.providers.million_verifier import MillionVerifierProvider
from src.enrichment.providers.hunter import HunterProvider


class TestMillionVerifier:
    def test_returns_unknown_without_api_key(self):
        provider = MillionVerifierProvider(api_key="")
        result = provider.verify("test@example.com")
        assert result.status == "unknown"

    @patch("src.enrichment.providers.million_verifier.requests.get")
    def test_ok_maps_to_valid(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": "ok", "email": "test@example.com"},
        )
        mock_get.return_value.raise_for_status = lambda: None
        provider = MillionVerifierProvider(api_key="fake-key")
        result = provider.verify("test@example.com")
        assert result.status == "valid"
        assert result.confidence == 1.0

    @patch("src.enrichment.providers.million_verifier.requests.get")
    def test_catch_all_maps_to_catch_all(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": "catch_all"},
        )
        mock_get.return_value.raise_for_status = lambda: None
        provider = MillionVerifierProvider(api_key="fake-key")
        result = provider.verify("test@catchall.com")
        assert result.status == "catch_all"
        assert result.confidence == 0.5

    @patch("src.enrichment.providers.million_verifier.requests.get")
    def test_invalid_maps_to_invalid(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": "invalid"},
        )
        mock_get.return_value.raise_for_status = lambda: None
        provider = MillionVerifierProvider(api_key="fake-key")
        result = provider.verify("bad@example.com")
        assert result.status == "invalid"

    @patch("src.enrichment.providers.million_verifier.requests.get")
    def test_network_error_returns_unknown(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("timeout")
        provider = MillionVerifierProvider(api_key="fake-key")
        result = provider.verify("test@example.com")
        assert result.status == "unknown"

    @patch("src.enrichment.providers.million_verifier.requests.get")
    def test_catch_all_is_never_verified(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": "catch_all"},
        )
        mock_get.return_value.raise_for_status = lambda: None
        provider = MillionVerifierProvider(api_key="fake-key")
        result = provider.verify("test@catchall.com")
        assert result.status != "valid"


class TestHunterProvider:
    def test_returns_none_without_api_key(self):
        provider = HunterProvider(api_key="")
        result = provider.find_email("empresa.com", "Juan", "Perez")
        assert result is None

    @patch("src.enrichment.providers.hunter.requests.get")
    def test_returns_email_and_score(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": {
                    "email": "juan.perez@empresa.com",
                    "score": 92,
                    "sources": [],
                }
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        provider = HunterProvider(api_key="fake-key")
        result = provider.find_email("empresa.com", "Juan", "Perez")
        assert result is not None
        assert result["email"] == "juan.perez@empresa.com"
        assert result["score"] == 92

    @patch("src.enrichment.providers.hunter.requests.get")
    def test_returns_none_when_no_email_found(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {}},
        )
        mock_get.return_value.raise_for_status = lambda: None
        provider = HunterProvider(api_key="fake-key")
        result = provider.find_email("empresa.com", "Juan", "Perez")
        assert result is None

    @patch("src.enrichment.providers.hunter.requests.get")
    def test_network_error_returns_none(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("timeout")
        provider = HunterProvider(api_key="fake-key")
        result = provider.find_email("empresa.com", "Juan", "Perez")
        assert result is None
