"""Fit: how well an item matches what the user is really after, with a threshold below which it's
dropped. A search for "UI/UX internships" should never fill a tab with senior roles.

Zero tokens and explainable: the level comes from the title ("intern", "junior", "senior", "staff"…),
the role from whether the title names it. A tab opts in with `fit: {level, roles, avoid, min}`.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Level = Literal["intern", "junior", "mid", "senior"]
# order matters: an "Associate Director" is senior, a "Senior Intern" is still an internship
LEVEL_RX: list[tuple[Level, re.Pattern]] = [
    ("intern", re.compile(r"\b(?:intern(?:ship)?s?|co-?op|apprentice(?:ship)?|trainee|working student|"
                          r"placement|summer 20\d\d)\b", re.IGNORECASE)),
    ("senior", re.compile(r"\b(?:senior|sr\.?|staff|principal|lead|head of|director|manager|vp|chief|"
                          r"architect)\b", re.IGNORECASE)),
    ("junior", re.compile(r"\b(?:junior|jr\.?|entry[- ]level|new grad(?:uate)?|graduate|associate|early career)\b",
                          re.IGNORECASE)),
]  # fmt: skip
# how well a role at one level suits someone after another (rows: wanted, columns: offered)
MATCH: dict[str, dict[str, float]] = {
    "intern": {"intern": 1, "junior": 0.5, "mid": 0.15, "senior": 0},
    "junior": {"junior": 1, "intern": 0.5, "mid": 0.6, "senior": 0},
    "mid": {"mid": 1, "junior": 0.6, "senior": 0.5, "intern": 0},
    "senior": {"senior": 1, "mid": 0.7, "junior": 0.1, "intern": 0},
}


class Fit(BaseModel):
    """What a search is for: a level and role words. Anything scoring under `min` is dropped."""

    level: Level | None = None  # what the user is after
    roles: list[str] = Field(default=[], max_length=12)  # e.g. ["ui designer", "ux designer"]
    avoid: list[str] = Field(default=[], max_length=12)  # never these words in a title
    min: float = Field(default=0.6, ge=0, le=1)  # items below this are dropped

    @field_validator("level", mode="before")
    @classmethod
    def _level(cls, v):
        return level_from_text(v) if isinstance(v, str) else v

    @field_validator("roles", "avoid", mode="before")
    @classmethod
    def _list(cls, v):
        if isinstance(v, str):
            v = v.split(",")
        return [x.strip().lower() for x in v or [] if x and x.strip()]


def level_of(title: str) -> Level:
    """The level a job title implies (intern, junior, mid, senior); 'mid' when it doesn't say."""
    return next((lvl for lvl, rx in LEVEL_RX if rx.search(title)), "mid")


def _stem(w: str) -> str:
    return re.sub(r"(?:ers?|ing|s)$", "", w) if len(w) > 5 else w


def _has(term: str, text: str) -> bool:
    """Every word of the term starts a word in the text, loosely ("product designer" matches
    "Product Design Internship", "ux designer" matches "UI/UX Designer")."""
    words = re.findall(r"[\w+#]+", term.lower())
    return bool(words) and all(re.search(rf"\b{re.escape(_stem(w))}", text, re.IGNORECASE) for w in words)


def score(fit: Fit, title: str, body: str = "") -> tuple[float, list[str]]:
    """0..1 and the reasons, e.g. (0.95, ["internship", "ux designer"]) or (0.0, ["senior role"])."""
    if any(_has(a, title) for a in fit.avoid):
        return 0.0, [f"not {next(a for a in fit.avoid if _has(a, title))}"]
    parts: list[tuple[float, float]] = []  # (weight, score)
    why: list[str] = []
    if fit.level:
        got = level_of(title)
        if MATCH[fit.level][got] == 0:  # an internship seeker never wants a senior role, and vice versa
            return 0.0, [f"{got} role"]
        parts.append((0.55, MATCH[fit.level][got]))
        if got != "mid" or fit.level == "mid":
            why.append({"intern": "internship", "junior": "entry level", "mid": "mid level",
                        "senior": "senior role"}[got])  # fmt: skip
    if fit.roles:
        in_title = next((r for r in fit.roles if _has(r, title)), None)
        in_body = next((r for r in fit.roles if _has(r, body)), None)
        parts.append((0.45, 1.0 if in_title else 0.5 if in_body else 0.0))
        if in_title or in_body:
            why.append(in_title or in_body)
    if not parts:
        return 1.0, []
    total = sum(w for w, _ in parts)
    return round(sum(w * s for w, s in parts) / total, 2), why


def keeps(fit: Fit | None, title: str, body: str = "") -> tuple[bool, float | None, list[str]]:
    """(keep it?, score, why) for a title against a tab's fit. No fit keeps everything."""
    if fit is None:
        return True, None, []
    s, why = score(fit, title, body)
    return s >= fit.min, s, why


# ---------------------------------------------------------------- from the user's own words


def level_from_text(text: str | None) -> Level | None:
    """'an internship', 'first job', 'senior roles' -> a level; 'not now' or nothing -> None."""
    t = (text or "").lower()
    if not t.strip() or re.search(r"\b(?:not now|no|nope|not looking)\b", t):
        return None
    if re.search(r"\bintern|co-?op|placement|trainee", t):
        return "intern"
    if re.search(r"\bsenior|staff|principal|lead\b", t):
        return "senior"
    if re.search(r"\bjunior|first job|entry|new grad|graduate|fresher", t):
        return "junior"
    if re.search(r"\bmid|experienced|\d+\+? years", t):
        return "mid"
    return None


FILLER = re.compile(
    r"\b(?:not now|an?|the|in|as|for|of|my|first|job|jobs|roles?|positions?|work|internships?|intern|junior|"
    r"senior|mid[- ]level|mid|entry[- ]level|level|new grad|graduate|remote|looking|some|any|or|and|"
    r"\d+\+? years?)\b",
    re.IGNORECASE,
)


def roles_from_text(text: str | None) -> list[str]:
    """'an internship in UI/UX design, or product design' -> ['ui/ux design', 'product design']."""
    out = []
    for part in re.split(r",|;|\bor\b|\band\b|/(?=\s)", text or "", flags=re.IGNORECASE):
        p = re.sub(r"\s+", " ", FILLER.sub(" ", part)).strip(" .-").lower()
        if len(p) > 1:
            out.append(p.replace("ui/ux", "ux").replace("ui ux", "ux"))
    return out[:6]


def profile(about: dict) -> dict:
    """What the user is after, from what they told New Game or Bolt. Explicit keys win."""
    asked = about.get("looking_for", "")
    roles = about.get("roles") or ", ".join(roles_from_text(asked))
    return {"level": level_from_text(about.get("level")) or level_from_text(asked), "roles": roles,
            "location": about.get("location", "")}  # fmt: skip
