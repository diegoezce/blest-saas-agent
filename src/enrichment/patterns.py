import re
import unicodedata


def _normalize(name: str) -> str:
    """Lowercase, strip accents, keep only ascii letters."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _slugify(part: str) -> str:
    return re.sub(r"[^a-z]", "", _normalize(part))


def generate_candidates(first: str, last: str, domain: str) -> list[str]:
    """Return email candidates ordered by prevalence."""
    f = _slugify(first)
    l = _slugify(last)
    if not f or not l:
        return []
    return [
        f"{f}.{l}@{domain}",
        f"{f[0]}{l}@{domain}",
        f"{f}@{domain}",
        f"{f}{l}@{domain}",
        f"{f[0]}.{l}@{domain}",
        f"{l}@{domain}",
    ]


def infer_pattern_from_emails(scraped_emails: list[str], domain: str) -> str | None:
    """
    Given emails found on a company site, return the pattern name that matches
    (one of: 'first.last', 'flast', 'first', 'firstlast', 'f.last', 'last').
    Returns None if no clear pattern found.
    """
    local_parts = [
        e.split("@")[0]
        for e in scraped_emails
        if e.endswith(f"@{domain}")
    ]
    if not local_parts:
        return None

    # count occurrences of structural patterns
    # f.last: exactly 1 letter, dot, then letters (e.g. c.garcia)
    # first.last: 2+ letters, dot, then letters (e.g. carlos.garcia)
    pattern_votes: dict[str, int] = {}
    for local in local_parts:
        if re.match(r"^[a-z]\.[a-z]+$", local):
            pattern_votes["f.last"] = pattern_votes.get("f.last", 0) + 1
        elif re.match(r"^[a-z]{2,}\.[a-z]+$", local):
            pattern_votes["first.last"] = pattern_votes.get("first.last", 0) + 1
        elif re.match(r"^[a-z][a-z]{3,}$", local):
            # could be 'flast' or 'firstlast' — hard to tell without names
            pattern_votes["flast"] = pattern_votes.get("flast", 0) + 1

    if not pattern_votes:
        return None
    return max(pattern_votes, key=lambda k: pattern_votes[k])


def prioritize_candidates(
    candidates: list[str],
    inferred_pattern: str | None,
    first: str,
    last: str,
    domain: str,
) -> list[str]:
    """Move the candidate matching the inferred pattern to the front."""
    if not inferred_pattern:
        return candidates

    f = _slugify(first)
    l = _slugify(last)
    pattern_map = {
        "first.last": f"{f}.{l}@{domain}",
        "flast": f"{f[0]}{l}@{domain}",
        "first": f"{f}@{domain}",
        "firstlast": f"{f}{l}@{domain}",
        "f.last": f"{f[0]}.{l}@{domain}",
        "last": f"{l}@{domain}",
    }
    preferred = pattern_map.get(inferred_pattern)
    if preferred and preferred in candidates:
        ordered = [preferred] + [c for c in candidates if c != preferred]
        return ordered
    return candidates
