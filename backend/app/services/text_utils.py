# text_utils.py — Shared text normalization utilities
import re
import unicodedata

NORMALIZE_REGEX_1 = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalize text preserving spaces across Roman and non-Roman scripts."""
    normalized = NORMALIZE_REGEX_1.sub(" ", text.lower()).strip()
    normalized = "".join(
        char
        for char in normalized
        if char.isalnum() or char.isspace() or unicodedata.category(char).startswith("M")
    )
    normalized = NORMALIZE_REGEX_1.sub(" ", normalized)
    return normalized.strip()


def collapse_text(text: str) -> str:
    """Collapse text for matching while preserving unicode word characters."""
    normalized = "".join(
        char
        for char in text.lower()
        if char.isalnum() or unicodedata.category(char).startswith("M")
    )
    normalized = NORMALIZE_REGEX_1.sub(" ", normalized).strip()
    return normalized
