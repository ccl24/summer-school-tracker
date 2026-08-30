"""Synchronize collector review items to GitHub Issues using the built-in token."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW_FILE = ROOT / "data" / "review_issues.json"


def request(method: str, endpoint: str, token: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        endpoint,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode() or "{}")


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        print("GitHub environment unavailable; skipping issue synchronization.")
        return
    reviews = json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
    base = f"https://api.github.com/repos/{repository}"
    existing = request("GET", f"{base}/issues?state=open&per_page=100", token)
    existing_by_title = {issue["title"]: issue for issue in existing if "pull_request" not in issue}
    wanted = {item["title"] for item in reviews}
    for item in reviews:
        if item["title"] not in existing_by_title:
            request("POST", f"{base}/issues", token, {"title": item["title"], "body": item["body"]})
    for title, issue in existing_by_title.items():
        if title.startswith("[review] ") and title not in wanted:
            request("PATCH", f"{base}/issues/{issue['number']}", token, {"state": "closed", "state_reason": "completed"})
    print(f"Synchronized {len(reviews)} review issue(s).")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as error:
        raise SystemExit(f"GitHub issue synchronization failed: {error}")

