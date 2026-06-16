import pytest
from src.enrichment.patterns import (
    generate_candidates,
    infer_pattern_from_emails,
    prioritize_candidates,
    _slugify,
    _normalize,
)


class TestNormalize:
    def test_strips_accents(self):
        assert _normalize("José") == "jose"

    def test_lowercases(self):
        assert _normalize("María") == "maria"

    def test_plain_ascii(self):
        assert _normalize("carlos") == "carlos"


class TestSlugify:
    def test_removes_non_alpha(self):
        assert _slugify("O'Brien") == "obrien"

    def test_accented_name(self):
        assert _slugify("González") == "gonzalez"

    def test_space_name(self):
        assert _slugify("de la Cruz") == "delacruz"


class TestGenerateCandidates:
    def test_returns_six_patterns(self):
        candidates = generate_candidates("Juan", "Perez", "empresa.com")
        assert len(candidates) == 6

    def test_patterns_contain_domain(self):
        candidates = generate_candidates("Juan", "Perez", "empresa.com")
        assert all("@empresa.com" in c for c in candidates)

    def test_known_patterns(self):
        candidates = generate_candidates("Juan", "Perez", "empresa.com")
        assert "juan.perez@empresa.com" in candidates
        assert "jperez@empresa.com" in candidates
        assert "juan@empresa.com" in candidates
        assert "juanperez@empresa.com" in candidates
        assert "j.perez@empresa.com" in candidates
        assert "perez@empresa.com" in candidates

    def test_accented_first_name(self):
        candidates = generate_candidates("María", "López", "empresa.com")
        assert "maria.lopez@empresa.com" in candidates
        assert "mlopez@empresa.com" in candidates

    def test_single_name_returns_first_only(self):
        # A single-name contact still gets the first-name pattern (only one possible).
        candidates = generate_candidates("Juan", "", "empresa.com")
        assert candidates == ["juan@empresa.com"]

    def test_empty_first_name_returns_empty(self):
        candidates = generate_candidates("", "Perez", "empresa.com")
        assert candidates == []


class TestInferPattern:
    def test_infers_first_dot_last(self):
        emails = ["carlos.garcia@empresa.com", "ana.ramirez@empresa.com"]
        pattern = infer_pattern_from_emails(emails, "empresa.com")
        assert pattern == "first.last"

    def test_infers_f_dot_last(self):
        emails = ["c.garcia@empresa.com", "a.ramirez@empresa.com"]
        pattern = infer_pattern_from_emails(emails, "empresa.com")
        assert pattern == "f.last"

    def test_returns_none_for_empty_list(self):
        assert infer_pattern_from_emails([], "empresa.com") is None

    def test_ignores_other_domain_emails(self):
        # emails from different domain should not influence pattern
        emails = ["info@otra.com", "ventas@otra.com"]
        # These don't end with @empresa.com so no vote is cast
        result = infer_pattern_from_emails(emails, "empresa.com")
        assert result is None


class TestPrioritizeCandidates:
    def test_moves_matching_pattern_to_front(self):
        candidates = generate_candidates("Juan", "Perez", "empresa.com")
        ordered = prioritize_candidates(candidates, "first.last", "Juan", "Perez", "empresa.com")
        assert ordered[0] == "juan.perez@empresa.com"

    def test_no_pattern_returns_original_order(self):
        candidates = generate_candidates("Juan", "Perez", "empresa.com")
        ordered = prioritize_candidates(candidates, None, "Juan", "Perez", "empresa.com")
        assert ordered == candidates

    def test_unknown_pattern_returns_original_order(self):
        candidates = generate_candidates("Juan", "Perez", "empresa.com")
        ordered = prioritize_candidates(candidates, "unknown_pattern", "Juan", "Perez", "empresa.com")
        assert ordered == candidates
