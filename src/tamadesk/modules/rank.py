"""Local taste ranking: a tiny word-weight model per module, learned from save/skip.

No ML runtime and no tokens. Each saved item adds +1 to its words, each skip -1; an item's score is
the sum of its words' smoothed log-odds plus a boost for the module's declared interests. Small
enough to run on every fetch, and explainable ("why: rust, compilers").
"""

from __future__ import annotations

import math
import re
import sqlite3

# fmt: off
STOP = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "your", "you", "are", "was", "were", "has", "have",
    "had", "not", "but", "all", "can", "will", "its", "our", "their", "they", "them", "into", "about", "over",
    "more", "most", "new", "how", "what", "why", "when", "who", "which", "using", "use", "used", "via", "one",
    "two", "get", "got", "just", "than", "then", "also", "out", "now", "may", "per", "any", "each", "like",
    "make", "made", "show",
})
# fmt: on
WORD = re.compile(r"[a-z][a-z0-9+#.-]{2,}")


def words(text: str) -> set[str]:
    """The meaningful words of a text, lowercased, without stop words."""
    return {w.strip(".-") for w in WORD.findall(text.lower())} - STOP


def score(conn: sqlite3.Connection, module: str, text: str, interests: list[str]) -> tuple[float, list[str]]:
    """(score, top reasons) for an item: learned word weights plus the tab's interests."""
    ws = words(text)
    if not ws:
        return 0.0, []
    marks = ",".join("?" * len(ws))
    rows = conn.execute(f"SELECT term, pos, neg FROM terms WHERE module = ? AND term IN ({marks})",
                        (module, *ws)).fetchall()  # fmt: skip
    parts = {r["term"]: math.log((r["pos"] + 1) / (r["neg"] + 1)) for r in rows}
    for i in interests:  # an interest counts when all its words show up ("machine learning systems")
        if (iw := words(i)) and iw <= ws:
            parts[i.lower()] = parts.get(i.lower(), 0) + 1.5
    top = sorted((k for k, v in parts.items() if v > 0.3), key=lambda k: -parts[k])[:3]
    return round(sum(parts.values()), 3), top


def learn(conn: sqlite3.Connection, module: str, text: str, liked: bool) -> None:
    """A bookmark (+1) or pass (-1) for each of the item's words."""
    col = "pos" if liked else "neg"
    conn.executemany(
        f"""INSERT INTO terms (module, term, {col}) VALUES (?, ?, 1)
            ON CONFLICT(module, term) DO UPDATE SET {col} = {col} + 1""",
        [(module, w) for w in words(text)],
    )


def taste(conn: sqlite3.Connection, module: str, n: int = 3) -> dict:
    """What the tab has learned, to show it: the words bookmarks and passes most agree on."""
    rows = conn.execute(
        "SELECT term, pos, neg FROM terms WHERE module = ? AND abs(pos - neg) >= 2", (module,)
    ).fetchall()
    lean = sorted(rows, key=lambda r: -abs(r["pos"] - r["neg"]))
    return {"more": [r["term"] for r in lean if r["pos"] > r["neg"]][:n],
            "less": [r["term"] for r in lean if r["neg"] > r["pos"]][:n]}  # fmt: skip
