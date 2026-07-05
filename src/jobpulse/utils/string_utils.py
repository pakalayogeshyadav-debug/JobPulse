"""jobpulse.utils.string_utils — String cleaning and normalisation utilities.

Pure functions for text processing operations used during transformation.
All functions are idempotent and have no side effects.

Functions:
    clean_text()            → Strip whitespace and fix common encoding issues
    normalise_job_title()   → Map raw titles to canonical categories
    slugify()               → Convert text to URL-safe slug
    extract_salary_number() → Parse salary strings like "$90k" to float

Usage:
    >>> from jobpulse.utils.string_utils import clean_text, normalise_job_title
    >>> clean_text("  Senior Data  Engineer  ")
    'Senior Data Engineer'
    >>> normalise_job_title("sr. data engneer")
    'Data Engineer'
"""

from __future__ import annotations

import re
import unicodedata


def clean_text(text: str | None) -> str | None:
    """Clean a text string by stripping whitespace and collapsing internal spaces.

    Args:
        text: Raw string to clean. May be None.

    Returns:
        str | None: Cleaned string, or None if input is None/empty.

    Example:
        >>> clean_text("  Data   Engineer  ")
        'Data Engineer'
        >>> clean_text(None) is None
        True
    """
    if text is None or not str(text).strip():
        return None
    # Collapse multiple internal whitespace characters
    return re.sub(r"\s+", " ", str(text).strip())


def normalise_job_title(title: str | float | None) -> str | None:
    """Normalise a raw job title to a canonical category string.
    Removes emojis and excessive duplicate words.
    """
    if not isinstance(title, str):
        return None

    # Remove emojis (common unicode blocks for emojis)
    cleaned = re.sub(r"[\U00010000-\U0010ffff]", "", title)

    # Clean text to remove extra whitespace
    cleaned_opt = clean_text(cleaned)
    if not cleaned_opt:
        return None
    lowered = cleaned_opt.lower()

    # Remove consecutive duplicate words
    words = lowered.split()
    deduped_words: list[str] = []
    for word in words:
        if not deduped_words or word != deduped_words[-1]:
            deduped_words.append(word)
    lowered_deduped = " ".join(deduped_words)

    _TITLE_PATTERNS: dict[str, list[str]] = {
        "Data Engineer": [
            "data engineer",
            "etl developer",
            "data pipeline",
            "data infrastructure",
            "analytics engineer",
        ],
        "Data Scientist": [
            "data scientist",
            "machine learning engineer",
            "ml engineer",
            "ai engineer",
            "research scientist",
            "applied scientist",
        ],
        "Data Analyst": [
            "data analyst",
            "business analyst",
            "bi analyst",
            "business intelligence",
            "reporting analyst",
        ],
        "MLOps Engineer": [
            "mlops",
            "ml ops",
            "machine learning ops",
            "model deployment",
            "ai platform",
        ],
        "Data Architect": [
            "data architect",
            "solutions architect",
            "cloud architect",
            "enterprise architect",
        ],
        "Database Administrator": [
            "database administrator",
            "dba",
            "postgres dba",
            "oracle dba",
        ],
        "Software Engineer": [
            "software engineer",
            "backend engineer",
            "full stack",
            "frontend engineer",
            "software developer",
            "java developer",
            "python developer",
        ],
        "Analytics Engineer": [
            "analytics engineer",
            "dbt engineer",
        ],
    }

    for canonical_title, patterns in _TITLE_PATTERNS.items():
        if any(pattern in lowered_deduped for pattern in patterns):
            return canonical_title

    # Return cleaned original (title-cased to look nice)
    return " ".join(w.capitalize() for w in deduped_words)


def slugify(text: str) -> str:
    """Convert a string to a URL-safe slug."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower()
    slugged = re.sub(r"[^\w\s-]", "", lowered)
    slugged = re.sub(r"[-\s]+", "-", slugged)
    return slugged.strip("-")


def extract_salary_number(salary_str: str | None) -> float | None:
    """Extract a numeric salary value from common formatted strings.
    Supports USD, EUR, GBP, INR, Lakhs, Crores, LPA.
    """
    if not salary_str:
        return None

    cleaned_lower = str(salary_str).lower().strip()

    multiplier = 1.0
    if "crore" in cleaned_lower or "cr" in cleaned_lower.split():
        multiplier = 10_000_000.0
        cleaned_lower = re.sub(r"\bcrores?\b", "", cleaned_lower)
        cleaned_lower = re.sub(r"\bcr\b", "", cleaned_lower)
    elif "lakh" in cleaned_lower or "lpa" in cleaned_lower:
        multiplier = 100_000.0
        cleaned_lower = re.sub(r"\blakhs?\b", "", cleaned_lower)
        cleaned_lower = re.sub(r"\blpa\b", "", cleaned_lower)
    elif "m" in cleaned_lower and not any(w in cleaned_lower for w in ["month", "mo"]):
        if re.search(r"\d\s*m\b", cleaned_lower):
            multiplier = 1_000_000.0
            cleaned_lower = re.sub(r"(\d)\s*m\b", r"\1", cleaned_lower)
    elif re.search(r"\d\s*k\b", cleaned_lower):
        multiplier = 1_000.0
        cleaned_lower = re.sub(r"(\d)\s*k\b", r"\1", cleaned_lower)

    cleaned = re.sub(r"[£$€₹,\s]|usd|inr|eur|gbp", "", cleaned_lower)
    cleaned = re.sub(r"[^0-9.]", "", cleaned)

    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None
