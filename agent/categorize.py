"""Keyword-based classification of opportunities into dashboard categories.

Runs before the LLM so the dashboard filter bar works even when evaluation is
disabled or the API key is missing. Rules are ordered: the first category with
a keyword hit wins, so put the most specific categories first.
"""

from __future__ import annotations

CATEGORY_EO_AI = "Earth Observation & AI"
CATEGORY_ROBOTICS = "Robotics & Software"
CATEGORY_SPACE_SYSTEMS = "Space Systems"
CATEGORY_SCIENCE = "Space Science"
CATEGORY_OPERATIONS = "Operations & Ground Segment"
CATEGORY_BUSINESS = "Business & Policy"
CATEGORY_OTHER = "Other"

ALL_CATEGORIES = (
    CATEGORY_EO_AI,
    CATEGORY_ROBOTICS,
    CATEGORY_SPACE_SYSTEMS,
    CATEGORY_SCIENCE,
    CATEGORY_OPERATIONS,
    CATEGORY_BUSINESS,
    CATEGORY_OTHER,
)

# Ordered (category, keywords) rules. Keywords are matched case-insensitively
# against the concatenated title/kind/summary text.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        CATEGORY_EO_AI,
        (
            "earth observation", "remote sensing", "artificial intelligence",
            "machine learning", " ai ", "ai in", "ai and", "spaice", "copernicus",
            "data science", "big data", "climate", "geospatial", "sar ",
            "hyperspectral", "digital twin",
        ),
    ),
    (
        CATEGORY_ROBOTICS,
        (
            "robotic", "autonom", "software", "on-board computer", "avionics software",
            "computer vision", "control system", "guidance", "navigation training",
            "gnc", "embedded", "flight software", "simulation",
        ),
    ),
    (
        CATEGORY_SPACE_SYSTEMS,
        (
            "cubesat", "spacecraft", "satellite", "propulsion", "thermal",
            "structure", "concurrent engineering", "systems engineering",
            "space power", "passive component", "radiation", "radecs", "antenna",
            "payload", "launcher", "rocket", "balloon", "rexus", "bexus",
            "testing", "assembly", "integration", "materials",
            "reliability", "availability", "maintainability",
            "product assurance", "quality assurance", "mechanism",
        ),
    ),
    (
        CATEGORY_SCIENCE,
        (
            "astronom", "astrophys", "planetary", "heliophys", "space science",
            "microgravity", "life science", "human spaceflight", "exploration",
            "cosmic", "physics",
        ),
    ),
    (
        CATEGORY_OPERATIONS,
        (
            "ground segment", "mission operations", "ground station", "flight dynamics",
            "telemetry", "space debris", "space safety", "space traffic",
            "operations", "esoc",
        ),
    ),
    (
        CATEGORY_BUSINESS,
        (
            "commercialisation", "commercialization", "entrepreneur", "business",
            "innovation", "policy", "law", "economics", "management", "procurement",
            "contracts", "finance",
        ),
    ),
)


# Weak fallbacks, applied only when no specific rule matched. Kept separate so
# a broad term like "engineer" can never outrank a precise one like "robotic".
_FALLBACK_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CATEGORY_SPACE_SYSTEMS, ("engineer", "engineering", "technician", "hardware")),
    (CATEGORY_OPERATIONS, ("officer", "analyst", "coordinator", "administrator")),
)


def categorize(*fragments: str) -> str:
    """Classify an opportunity from any number of text fragments."""
    haystack = " ".join(f" {f} " for f in fragments if f).lower()
    if not haystack.strip():
        return CATEGORY_OTHER
    for rules in (_RULES, _FALLBACK_RULES):
        for category, keywords in rules:
            if any(keyword in haystack for keyword in keywords):
                return category
    return CATEGORY_OTHER
