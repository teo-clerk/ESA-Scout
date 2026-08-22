"""Build the user's profile from a CV PDF and their public GitHub activity.

PDF text is extracted with pypdf, falling back to pdfplumber (slower but more
tolerant of unusual layouts). The extracted text is then split into sections by
their upper-case headings, which is how virtually every CV is structured.

Nothing here raises on bad input: a missing PDF or an unreachable GitHub API
yields a `Profile` carrying an `error` string, and the pipeline continues with a
degraded — but still useful — evaluation.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

import httpx

from .config import GITHUB_API_URL, Settings
from .models import GitHubProfile, Profile, Repository

LOGGER = logging.getLogger(__name__)

# Filenames that look like a CV, most specific first.
_PDF_NAME_HINTS = ("cv", "resume", "resumé", "profile", "curriculum")
_MAX_REPOS = 20
_MAX_SECTION_ITEMS = 12
_MAX_SKILLS = 40

# CV heading -> logical section. Matched against upper-case-only lines.
_SECTION_ALIASES: dict[str, str] = {
    "professional summary": "summary",
    "summary": "summary",
    "profile": "summary",
    "about": "summary",
    "education": "education",
    "academic background": "education",
    "skills": "skills",
    "technical skills": "skills",
    "competencies": "skills",
    "professional experience": "experience",
    "experience": "experience",
    "work experience": "experience",
    "employment": "experience",
    "projects & initiatives": "projects",
    "projects": "projects",
    "personal projects": "projects",
    "certifications": "certifications",
    "certificates": "certifications",
    "languages & interests": "interests",
    "interests": "interests",
    "publications": "projects",
}

# A heading line: mostly upper-case, short, no trailing sentence punctuation.
_HEADING_RE = re.compile(r"^[A-Z][A-Z\s&/,'\-–—.()]{2,60}$")
_BULLET_RE = re.compile(r"^[\s•▪◦\-–—*·]+")
_LABEL_RE = re.compile(r"^[A-Z][A-Za-z &/]{2,40}:\s*")


# --- PDF discovery & extraction -------------------------------------------
def find_profile_pdf(search_dirs: tuple[Path, ...]) -> Path | None:
    """Locate the most likely CV PDF across the configured directories."""
    candidates: list[Path] = []
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        candidates.extend(sorted(p for p in directory.glob("*.pdf") if p.is_file()))

    if not candidates:
        return None

    def rank(path: Path) -> tuple[int, int]:
        name = path.stem.lower()
        for index, hint in enumerate(_PDF_NAME_HINTS):
            if hint in name:
                return (index, len(name))
        return (len(_PDF_NAME_HINTS), len(name))

    return sorted(candidates, key=rank)[0]


def _glue_ratio(text: str) -> float:
    """Fraction of tokens that look like several words run together.

    Justified CV layouts frequently make extractors drop inter-word spaces
    ("humancenteredsolutionsthrough"). Counting improbably long tokens is a
    cheap, layout-agnostic proxy for extraction quality: lower is better.
    """
    tokens = text.split()
    if not tokens:
        return 1.0
    glued = sum(1 for token in tokens if len(token) > 20)
    return glued / len(tokens)


def _extract_with_pdfplumber(path: Path) -> str:
    import pdfplumber

    # x_tolerance=1.5 is tighter than the default and recovers spaces that
    # justified text would otherwise lose.
    with pdfplumber.open(str(path)) as pdf:
        pages = [page.extract_text(x_tolerance=1.5) or "" for page in pdf.pages]
    return "\n".join(pages).strip()


def _extract_with_pypdf(path: Path) -> str:
    import pypdf

    reader = pypdf.PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def extract_pdf_text(path: Path) -> tuple[str, str]:
    """Return (text, error).

    Both backends are attempted and the cleaner result wins, rather than
    trusting a fixed order: which extractor handles a given PDF best depends on
    how that PDF was produced.
    """
    errors: list[str] = []
    candidates: list[tuple[float, str]] = []

    for name, extractor in (
        ("pdfplumber", _extract_with_pdfplumber),
        ("pypdf", _extract_with_pypdf),
    ):
        try:
            text = extractor(path)
        except Exception as exc:
            errors.append(f"{name} failed: {exc}")
            continue
        if text:
            candidates.append((_glue_ratio(text), text))
        else:
            errors.append(f"{name} extracted no text")

    if not candidates:
        return "", "; ".join(errors) or "no PDF backend produced text"

    candidates.sort(key=lambda pair: pair[0])
    return repair_text(candidates[0][1]), ""


# Standalone accent glyphs emitted before their base letter, e.g. "Fundaci´o".
_ACCENTS = {"´": "́", "`": "̀", "¨": "̈", "ˆ": "̂", "˜": "̃"}
_ACCENT_RE = re.compile(f"[{''.join(_ACCENTS)}]([a-zA-Z])")


def repair_text(text: str) -> str:
    """Repair common PDF text-extraction artifacts.

    Two are near-universal in CV PDFs: accents emitted as a standalone glyph
    *before* their base letter, and a missing space before an opening bracket.
    Line-break hyphenation is handled later in `_reflow`, where we still know
    which join was a line break.
    """
    if not text:
        return text

    def _recombine(match: re.Match[str]) -> str:
        accent = _ACCENTS[match.group(0)[0]]
        return unicodedata.normalize("NFC", match.group(1) + accent)

    repaired = _ACCENT_RE.sub(_recombine, text)
    repaired = re.sub(r"(?<=[a-zA-Z])\(", " (", repaired)
    return repaired


# --- CV structure ----------------------------------------------------------
def _normalise_heading(line: str) -> str | None:
    """Return the logical section name when `line` is a known CV heading."""
    stripped = line.strip().rstrip(":").strip()
    if not stripped or len(stripped) > 60:
        return None
    if not _HEADING_RE.match(stripped):
        return None
    lowered = stripped.lower()
    for alias, section in _SECTION_ALIASES.items():
        if lowered == alias or lowered.startswith(alias):
            return section
    return None


def split_sections(text: str) -> dict[str, list[str]]:
    """Split raw CV text into {section_name: [lines]}."""
    sections: dict[str, list[str]] = {}
    current = "header"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = _normalise_heading(line)
        if heading:
            current = heading
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _clean_item(line: str) -> str:
    return _BULLET_RE.sub("", line).strip(" .;")


_BULLET_START_RE = re.compile(r"^[•▪◦*·]|^[-–—]\s")
_SENTENCE_END_RE = re.compile(r"[.!?:]$")
_MAX_ENTRY_CHARS = 400


def _reflow(lines: list[str]) -> list[str]:
    """Rejoin wrapped CV lines into whole entries.

    PDF extraction yields one string per visual line, so a single bullet is
    split mid-sentence. When a section uses bullet markers, each marker starts a
    new entry and everything up to the next marker belongs to it. Without
    markers we fall back to sentence-terminator detection.
    """
    has_bullets = any(_BULLET_START_RE.match(line.strip()) for line in lines)
    entries: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        starts_entry = (
            _BULLET_START_RE.match(stripped) is not None
            if has_bullets
            else (not entries or _SENTENCE_END_RE.search(entries[-1]) is not None)
        )
        cleaned = _clean_item(stripped)
        if not cleaned:
            continue
        if starts_entry or not entries:
            entries.append(cleaned)
        elif entries[-1].endswith("-") and cleaned[:1].islower():
            # A hyphen at a line break splits one word ("coun-" + "tries").
            entries[-1] = entries[-1][:-1] + cleaned
        else:
            entries[-1] = f"{entries[-1]} {cleaned}".strip()

    return [entry[:_MAX_ENTRY_CHARS].strip() for entry in entries]


def _take(lines: list[str], limit: int) -> tuple[str, ...]:
    """First `limit` reflowed entries from a section."""
    items = [entry for entry in _reflow(lines) if len(entry) >= 8]
    return tuple(items[:limit])


def _extract_skills(lines: list[str]) -> tuple[str, ...]:
    """Flatten a skills section into individual skill tokens.

    Handles the common "Programming: Python, C++, Java" label form as well as
    plain comma-separated lists.
    """
    skills: list[str] = []
    seen: set[str] = set()
    for line in lines:
        cleaned = _LABEL_RE.sub("", _clean_item(line))
        for token in re.split(r"[,;•|]", cleaned):
            skill = token.strip(" .()")
            if not (2 <= len(skill) <= 45):
                continue
            key = skill.lower()
            if key in seen:
                continue
            seen.add(key)
            skills.append(skill)
            if len(skills) >= _MAX_SKILLS:
                return tuple(skills)
    return tuple(skills)


def _extract_name(sections: dict[str, list[str]]) -> str:
    for line in sections.get("header", []):
        candidate = _clean_item(line)
        # A name line has no digits and no contact punctuation.
        if candidate and not re.search(r"[\d@|]", candidate) and len(candidate) <= 60:
            return candidate
    return ""


def _extract_headline(sections: dict[str, list[str]]) -> str:
    summary = " ".join(sections.get("summary", []))
    if not summary:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", summary.strip())[0]
    return sentence.strip()[:280]


def parse_cv(text: str, source_file: str = "") -> Profile:
    """Turn extracted CV text into a structured `Profile` (no GitHub data)."""
    sections = split_sections(text)
    highlights = _take(sections.get("experience", []), _MAX_SECTION_ITEMS // 2) + _take(
        sections.get("projects", []), _MAX_SECTION_ITEMS // 2
    )
    return Profile(
        name=_extract_name(sections),
        headline=_extract_headline(sections),
        source_file=source_file,
        education=_take(sections.get("education", []), _MAX_SECTION_ITEMS),
        skills=_extract_skills(sections.get("skills", [])),
        highlights=highlights,
        raw_text=text,
    )


# --- GitHub ----------------------------------------------------------------
def fetch_github(
    username: str | None,
    token: str | None = None,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> GitHubProfile:
    """Fetch public repositories for `username`.

    Returns a `GitHubProfile` with `error` populated on any failure — GitHub
    being unreachable must not abort a scouting run.
    """
    if not username:
        return GitHubProfile(error="GITHUB_USERNAME not configured")

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    owns_client = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        response = client.get(
            f"{GITHUB_API_URL}/users/{username}/repos",
            params={"sort": "pushed", "direction": "desc", "per_page": "100"},
            headers=headers,
        )
        if response.status_code == 404:
            return GitHubProfile(username=username, error="GitHub user not found")
        if response.status_code == 403:
            return GitHubProfile(
                username=username,
                error="GitHub API rate limit reached (set GITHUB_TOKEN to raise it)",
            )
        if response.status_code >= 400:
            return GitHubProfile(
                username=username, error=f"GitHub API returned HTTP {response.status_code}"
            )
        payload = response.json()
    except Exception as exc:
        return GitHubProfile(username=username, error=f"GitHub request failed: {exc}")
    finally:
        if owns_client:
            client.close()

    if not isinstance(payload, list):
        return GitHubProfile(username=username, error="Unexpected GitHub API response")

    repos = tuple(
        Repository(
            name=str(item.get("name") or ""),
            description=str(item.get("description") or ""),
            language=str(item.get("language") or ""),
            url=str(item.get("html_url") or ""),
            stars=int(item.get("stargazers_count") or 0),
            topics=tuple(str(t) for t in (item.get("topics") or [])),
            pushed_at=str(item.get("pushed_at") or ""),
        )
        for item in payload
        if isinstance(item, dict) and not item.get("fork")
    )[:_MAX_REPOS]

    languages: list[str] = []
    for repo in repos:
        if repo.language and repo.language not in languages:
            languages.append(repo.language)

    return GitHubProfile(
        username=username,
        profile_url=f"https://github.com/{username}",
        repos=repos,
        languages=tuple(languages),
    )


# --- Entry point -----------------------------------------------------------
def build_profile(settings: Settings, client: httpx.Client | None = None) -> Profile:
    """Assemble the full profile: CV PDF + GitHub."""
    pdf_path = find_profile_pdf(settings.profile_dirs)
    if pdf_path is None:
        searched = ", ".join(str(d) for d in settings.profile_dirs)
        LOGGER.warning("no CV PDF found in %s", searched)
        profile = Profile(error=f"No PDF found in: {searched}")
    else:
        LOGGER.info("parsing CV from %s", pdf_path)
        text, error = extract_pdf_text(pdf_path)
        if not text:
            profile = Profile(source_file=pdf_path.name, error=error or "empty PDF")
        else:
            profile = parse_cv(text, source_file=pdf_path.name)

    github = fetch_github(
        settings.github_username,
        token=settings.github_token,
        timeout=settings.timeout,
        client=client,
    )
    if github.error:
        LOGGER.warning("GitHub sync degraded: %s", github.error)
    else:
        LOGGER.info("fetched %s GitHub repositories", len(github.repos))

    from dataclasses import replace

    return replace(profile, github=github)
