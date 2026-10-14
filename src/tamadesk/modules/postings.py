"""Job postings: find them by search, keep only originals, learn which company job boards they live on,
and make sure they're still open. Zero tokens; the pure parts here are easy to test.

Measured on a real internship search (docs/use-cases.md): one combined search query found nothing,
four posting-shaped queries found 20 with 8 good, 60% of searched postings were closed or
unreachable, and company job boards were always original and open. So: many narrow queries,
originals only, then watch the boards the results came from, and check what's still open.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from tamadesk.modules.fit import Fit

# the applicant tracking systems with public, login-free job lists (see sources.BOARDS)
ATS_HOST = re.compile(
    r"(?:^|\.)(?:greenhouse\.io|lever\.co|ashbyhq\.com|workable\.com|smartrecruiters\.com|recruitee\.com|"
    r"teamtailor\.com|bamboohr\.com|breezy\.hr|myworkdayjobs\.com|jobvite\.com|icims\.com|personio\.(?:de|com)|"
    r"rippling\.com|pinpointhq\.com|workday\.com)$",
    re.IGNORECASE,
)
# pages that list other people's jobs: boards, aggregators, school career centres
BOARD_HOST = re.compile(
    r"\.edu$|\.ac\.[a-z]{2}$|jobs?board|job-?board|(?:^|[.-])(?:jobs?|careers?|hiring|talent|recruit|intern|"
    r"internships?|remote|work|vacanc|gigs?)[a-z]*\.(?:com|io|co|net|org|ai|app|jobs|[a-z]{2})$|remoteok|weworkremotely|"
    r"remotive|wellfound|builtin|otta|welcometothejungle|simplyhired|monster\.|careerbuilder|jooble|adzuna|"
    r"talent\.com|jobera|internearn|internexxus|bestkaam|broxer|hiring\.camp|uiuxjobsboard|dribbble\.com/jobs|"
    r"glassdoor|indeed|ziprecruiter|linkedin|naukri|internshala|angel\.co|confidential\.careers|mediabistro|tealhq|"
    r"mysmartpros|dedyn\.io|zya\.me|github\.com|gitlab\.com|medium\.com|substack\.com",
    re.IGNORECASE,
)
# third-party job pages (/job/123, /job-detail/…), and portfolio boards that list other companies' jobs
# (jobs.some-vc.com/jobs/<company>/<id>)
THIRD_PARTY_PATH = re.compile(r"/(?:job|job-detail|remote-jobs)/", re.IGNORECASE)
PORTFOLIO_PATH = re.compile(r"^/(?:jobs|companies)/([a-z][\w-]*)/[\w-]{4,}", re.IGNORECASE)
POSTING_PATH = re.compile(
    r"/(?:careers?|jobs?|positions?|openings?|roles?|join(?:-us)?|vacanc\w*)/[^/?#]{3,}", re.IGNORECASE
)
CLOSED = re.compile(
    r"no longer (?:accepting|available|open|active)|(?:position|role|job) (?:has been |is )?(?:filled|closed)|"
    r"(?:job|posting|position) (?:is )?(?:not found|expired|unavailable)|this job has expired|applications? (?:are |is )?closed|"
    r"page (?:you(?:'re| are) looking for )?(?:can(?:no|')t be found|not found|does(?:n't| not) exist)",
    re.IGNORECASE,
)


def host(url: str) -> str:
    """A URL's host without 'www.'."""
    return re.sub(r"^www\.", "", url.split("/")[2].lower()) if url.count("/") >= 2 else ""


def kind(url: str) -> str:
    """ats (a company's job system) | careers (a posting on the company's own site) | board | other."""
    h = host(url)
    path = "/" + url.split("/", 3)[3] if url.count("/") >= 3 else "/"
    if ATS_HOST.search(h):
        return "ats"
    if BOARD_HOST.search(h) or THIRD_PARTY_PATH.search(path):
        return "board"
    if (
        h.startswith(("jobs.", "careers."))
        and (m := PORTFOLIO_PATH.match(path))
        and m.group(1).lower() not in h
    ):
        return "board"
    if h.endswith(".careers") or POSTING_PATH.search(path):
        return "careers"
    return "other"


def original(url: str) -> bool:
    """A posting at the source: the company's job system or its own careers pages. Never a board."""
    return kind(url) in ("ats", "careers")


# a link on a company job system -> (system, the company's id there), so its whole board can be watched
BOARD_URL = [
    (
        "greenhouse",
        re.compile(r"(?:job-)?boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([\w-]+)", re.IGNORECASE),
    ),
    ("lever", re.compile(r"jobs\.lever\.co/([\w.-]+)", re.IGNORECASE)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)", re.IGNORECASE)),
    ("workable", re.compile(r"apply\.workable\.com/([\w-]+)", re.IGNORECASE)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)", re.IGNORECASE)),
    ("recruitee", re.compile(r"([\w-]+)\.recruitee\.com", re.IGNORECASE)),
]
NOT_A_COMPANY = {"embed", "api", "v1", "jobs", "j", "o", "apply", "careers", "widget"}


def board_of(url: str) -> tuple[str, str] | None:
    """(job system, company id) for a link on a company job board, so the whole board can be watched."""
    for ats, rx in BOARD_URL:
        if (m := rx.search(url)) and m.group(1).lower() not in NOT_A_COMPANY:
            return ats, m.group(1)
    return None


LEVEL_WORDS = {"intern": "internship", "junior": "junior", "mid": "", "senior": "senior"}


def queries(fit: Fit | None, roles: list[str], location: str = "", limit: int = 6) -> list[str]:
    """Several posting-shaped queries (a search engine finds "a page like this" best), one per role,
    instead of one long comma list, which measured worse than nothing."""
    level = LEVEL_WORDS.get(fit.level, "") if fit and fit.level else ""
    roles = roles or (fit.roles if fit else []) or ["software engineer"]
    where = f", {location}" if location else ""
    first, second = [], []
    for r in roles:
        role = r if not level or level in r.lower() else f"{r} {'intern' if level == 'internship' else level}"
        first.append(f"{role.strip()} job posting{where}, apply on the company's careers page")
        second.append(f"a company hiring a {role.strip()}{where}: the open role on their careers page")
    # one phrasing per role first; a second phrasing fills the rest (two phrasings find different postings)
    return list(dict.fromkeys(first + second))[:limit]


OBJECTIVE = (
    "Rank first: a single, currently open job posting page for one role, on the hiring company's own careers site "
    "or its applicant tracking system (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee). Exclude job "
    "boards, aggregators, lists of jobs, university career centres, articles, LinkedIn, and closed postings."
)


def page_state(html: str) -> str:
    """open | closed, from a posting page's text."""
    text = re.sub(r"<[^>]+>", " ", html)[:30000]
    return "closed" if CLOSED.search(text) else "open"


def too_old(published: str, max_age_days: int | None, now: datetime | None = None) -> bool:
    """A posting older than this is usually filled. Unknown dates are given the benefit of the doubt."""
    if not published or not max_age_days:
        return False
    try:
        when = datetime.fromisoformat(published.replace("Z", "+00:00")[:25])
    except ValueError:
        return False
    when = when if when.tzinfo else when.replace(tzinfo=UTC)
    return when < (now or datetime.now(UTC)) - timedelta(days=max_age_days)
