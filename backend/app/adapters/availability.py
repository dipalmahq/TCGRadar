"""Product-level preorder evidence; a release announcement alone is not stock."""
from datetime import datetime, timezone
import re

from bs4 import BeautifulSoup


def preorder_evidence(title_labels, description="", now=None):
    words = r"vorbestell\w*|vorverkauf|pre[ -]?order\w*|pre[ -]?sale"
    if re.search(r"\b(?:" + words + r")\b", title_labels, re.I):
        return True
    text = BeautifulSoup(description, "html.parser").get_text(" ", strip=True)
    # Product descriptions need an explicit positive statement, not a generic FAQ
    # mentioning orders that happen to contain other preorder products.
    if re.search(r"\b(?:dieser artikel|dieses produkt|this item|this product)\s+(?:ist|is)\s+(?:eine?\s+|an?\s+)?(?:" + words + r")\b", text, re.I):
        return True
    match = re.search(r"\b(?:release(?: date)?|erscheinungsdatum|erscheint(?: am)?)\s*:?\s*(\d{1,2})[./](\d{1,2})[./](20\d{2})\b", text, re.I)
    if match:
        try:
            release = datetime(int(match[3]), int(match[2]), int(match[1]), tzinfo=timezone.utc)
            return release.date() > (now or datetime.now(timezone.utc)).date()
        except ValueError:
            pass
    return False
