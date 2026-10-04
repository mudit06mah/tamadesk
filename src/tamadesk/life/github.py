"""The user's open GitHub work (PRs, assigned issues, review requests) via their own `gh` login.

No token is stored here: `gh` already holds the user's auth. Cached briefly to stay fast.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta

QUERY = """query($n: Int!, $shipped: String!) {
  viewer { login }
  prs: search(query: "is:pr is:open author:@me archived:false sort:updated-desc", type: ISSUE, first: $n) {
    nodes { ... on PullRequest { title url number isDraft updatedAt reviewDecision repository { nameWithOwner }
      comments { totalCount } commits(last: 1) { nodes { commit { statusCheckRollup { state } } } } } } }
  issues: search(query: "is:issue is:open assignee:@me archived:false sort:updated-desc", type: ISSUE, first: $n) {
    nodes { ... on Issue { title url number updatedAt repository { nameWithOwner } comments { totalCount } } } }
  reviews: search(query: "is:pr is:open review-requested:@me archived:false sort:updated-desc", type: ISSUE, first: $n) {
    nodes { ... on PullRequest { title url number updatedAt isDraft author { login } repository { nameWithOwner } } } }
  shipped: search(query: $shipped, type: ISSUE, first: $n) {
    nodes { ... on PullRequest { title url number updatedAt repository { nameWithOwner } } } }
  me: viewer { repositories(first: 15, ownerAffiliations: OWNER, orderBy: {field: PUSHED_AT, direction: DESC}) {
    nodes { nameWithOwner url pushedAt stargazerCount isArchived isFork issues(states: OPEN) { totalCount } } } }
}"""
_cache: dict = {"at": 0.0, "data": None}


def _row(n: dict) -> dict:
    commits = (n.get("commits") or {}).get("nodes") or []
    rollup = (commits[0]["commit"].get("statusCheckRollup") or {}) if commits else {}
    return {
        "title": n["title"], "url": n["url"], "number": n["number"], "repo": n["repository"]["nameWithOwner"],
        "updated_at": n.get("updatedAt", ""), "draft": n.get("isDraft", False), "review": n.get("reviewDecision"),
        "checks": rollup.get("state"), "comments": (n.get("comments") or {}).get("totalCount", 0),
        "author": (n.get("author") or {}).get("login"),
    }  # fmt: skip


def status(refresh: bool = False, n: int = 30) -> dict:
    if not refresh and _cache["data"] and time.monotonic() - _cache["at"] < 300:
        return _cache["data"]
    if not shutil.which("gh"):
        return {
            "error": "GitHub CLI not found. Install `gh` and run `gh auth login` to track your PRs and issues."
        }
    week = (datetime.now(UTC).astimezone().date() - timedelta(days=7)).isoformat()
    proc = subprocess.run(["gh", "api", "graphql", "-f", f"query={QUERY}", "-F", f"n={n}",
                           "-f", f"shipped=is:pr author:@me is:merged merged:>={week}"],
                          capture_output=True, text=True, timeout=30, check=False)  # fmt: skip
    try:
        d = json.loads(proc.stdout or "{}").get("data") or {}
    except ValueError:
        d = {}
    if not d.get("viewer"):  # nothing usable came back (not logged in, network, ...)
        hint = (
            "gh isn't logged in (run `gh auth login`)"
            if "auth login" in proc.stderr
            else proc.stderr.strip()[-300:]
        )
        return {"error": hint or "GitHub didn't answer; try again in a minute"}
    data = {
        "login": d["viewer"]["login"],
        # a partial failure (e.g. a SAML-protected org) leaves one list empty instead of breaking the page
        **{k: [_row(x) for x in (d.get(k) or {}).get("nodes", []) if x] for k in ("prs", "issues", "reviews", "shipped")},
        "repos": [{"repo": r["nameWithOwner"], "url": r["url"], "pushed_at": r["pushedAt"], "stars": r["stargazerCount"],
                   "open_issues": r["issues"]["totalCount"]}
                  for r in ((d.get("me") or {}).get("repositories") or {}).get("nodes", [])
                  if r and not r["isArchived"] and not r["isFork"]],
    }  # fmt: skip
    _cache.update(at=time.monotonic(), data=data)
    return data
