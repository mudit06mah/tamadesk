import base64
import json

from tamadesk.assistant import runner, tools
from tamadesk.core import db
from tamadesk.core.config import get_settings
from tamadesk.life import github

B64 = base64.b64encode(b"Acme Sketch is a whiteboard for remote design teams. Pricing starts at $8.").decode()


def test_docs_upload_list_read_and_prompt(client):
    assert (
        client.post("/api/docs", json={"name": "brief.md", "kind": "product", "data_b64": B64}).status_code
        == 200
    )
    assert (
        client.post(
            "/api/docs", json={"name": "x.txt", "data_b64": base64.b64encode(b"hi").decode()}
        ).status_code
        == 422
    )
    (d,) = client.get("/api/docs").json()
    assert (d["name"], d["kind"]) == ("brief.md", "product")
    s = get_settings()
    assert "whiteboard" in tools.call(s, "read_doc", {"ref": "product"})
    conn = db.connect(s.db_path)
    prompt = runner.system_prompt(s, conn)
    assert (
        "brief.md (product" in prompt and "whiteboard" not in prompt
    )  # listed, not pasted: no tokens until needed


def test_github_status_maps_rows(monkeypatch):
    payload = {"data": {"viewer": {"login": "sam"}, "issues": {"nodes": []}, "reviews": {"nodes": []}, "prs": {"nodes": [{
        "title": "Fix it", "url": "u", "number": 3, "isDraft": True, "updatedAt": "2026-10-01T00:00:00Z",
        "reviewDecision": "CHANGES_REQUESTED", "repository": {"nameWithOwner": "a/b"}, "comments": {"totalCount": 2},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "FAILURE"}}}]}}]}}}  # fmt: skip

    class P:
        returncode, stdout, stderr = 0, json.dumps(payload), ""

    monkeypatch.setattr(github.shutil, "which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr(github.subprocess, "run", lambda *a, **k: P())
    (pr,) = github.status(refresh=True)["prs"]
    assert (pr["repo"], pr["draft"], pr["review"], pr["checks"], pr["comments"]) == (
        "a/b",
        True,
        "CHANGES_REQUESTED",
        "FAILURE",
        2,
    )
    monkeypatch.setattr(github.shutil, "which", lambda _: None)
    assert "gh" in github.status(refresh=True)["error"]
