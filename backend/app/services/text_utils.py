# text_utils.py — Shared text normalization utilities
import re

NORMALIZE_REGEX_1 = re.compile(r"\s+")
NORMALIZE_REGEX_2 = re.compile(r"[^a-z0-9 ]+")
# Collapsing version: removes ALL non-alphanumeric (used for field/path matching)
_COLLAPSE_REGEX = re.compile(r"[^a-z0-9]+")


def normalize_text(text: str) -> str:
    """Normalize text preserving spaces: lowercase, remove non-alphanumeric, collapse whitespace."""
    normalized = NORMALIZE_REGEX_1.sub(" ", text.lower()).strip()
    normalized = NORMALIZE_REGEX_2.sub("", normalized)
    return normalized.strip()


def collapse_text(text: str) -> str:
    """Collapse text for matching: lowercase, remove all non-alphanumeric, collapse whitespace."""
    normalized = _COLLAPSE_REGEX.sub("", text.lower())
    normalized = NORMALIZE_REGEX_1.sub(" ", normalized).strip()
    return normalized
