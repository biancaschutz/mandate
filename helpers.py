"""General helper functions

Strip html, build regex patterns for cleanup, etc.
"""

import html
import re

TAGS = re.compile(r"<[^>]+>")
WHITESPACE = re.compile(r"\s+")

INTERN = re.compile(r"\bintern(?:s|ship|ships|ed|ing)?\b", re.IGNORECASE)

def strip_html(text: str) -> str:
    """Strip HTML tags and extra whitespaces
    
    Scraped qualifications strings typically contain html tags, want to eliminate those
    """
    if not text:
        return ""
    text = TAGS.sub(" ", html.unescape(text))
    return WHITESPACE.sub(" ", text).strip()


def build_pattern(phrases: list[str]) -> str:
    """Build regex patterns
    
    Builds regex patterns of strings (or patterns that are already regex)
    """
    parts = [p if ("'" in p or "?" in p) else re.escape(p) for p in phrases]
    return r"\b(?:" + "|".join(parts) + r")\b"

def pick_value(numbers: list[int], strategy: str = "max"):
    if not numbers:
        return None
    if strategy == "min":
        return min(numbers)
    if strategy == "first":
        return numbers[0]
    return max(numbers)