"""Fetch, parse, validate, and persist official summer-program dates.

The collector intentionally uses explicit source adapters instead of discovery or search.
When a source cannot be parsed safely, it preserves prior verified data and emits a
review item for the GitHub Actions issue manager.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
try:
    from bs4 import BeautifulSoup
except ImportError:  # Local test fallback; CI installs BeautifulSoup from requirements.txt.
    BeautifulSoup = None

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PROGRAMS_FILE = DATA / "programs.json"
SOURCES_FILE = DATA / "sources.json"
STATE_FILE = DATA / "source-state.json"
REVIEW_FILE = DATA / "review_issues.json"
OVERRIDES_FILE = DATA / "manual-overrides.json"
USER_AGENT = "IvySummerTracker/1.0 (+https://github.com/your-account/ivy-summer-tracker)"
TIMEOUT_SECONDS = 20
ROBOTS_CACHE: dict[str, RobotFileParser] = {}

MONTHS = {
    name: index
    for index, name in enumerate(
        ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1
    )
}
DATE_RE = re.compile(
    r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(20\d{2})\b",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b", re.IGNORECASE)


class ParseFailure(Exception):
    pass


@dataclass
class ParseResult:
    open_date: dict[str, Any] | None = None
    deadlines: list[dict[str, Any]] | None = None
    status: str | None = None
    source_text: str = ""


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_text(html: str) -> str:
    if BeautifulSoup is None:
        class TextOnlyParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts: list[str] = []

            def handle_data(self, data: str) -> None:
                self.parts.append(data)

        parser = TextOnlyParser()
        parser.feed(html)
        return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def robots_url_for(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


def allowed_by_robots(url: str) -> bool:
    robots_url = robots_url_for(url)
    parser = ROBOTS_CACHE.get(robots_url)
    if parser is None:
        response = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS)
        if response.status_code == 404:
            return True
        response.raise_for_status()
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        ROBOTS_CACHE[robots_url] = parser
    return parser.can_fetch(USER_AGENT, url)


def fetch(url: str) -> str:
    if not allowed_by_robots(url):
        raise ParseFailure("robots.txt does not permit this collector to fetch the source page")
    response = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def normalize_date(match: re.Match[str], raw: str, timezone: str = "ET") -> dict[str, Any]:
    month = MONTHS[match.group(1).title()]
    iso_date = f"{match.group(3)}-{month:02d}-{int(match.group(2)):02d}"
    time_match = TIME_RE.search(raw)
    time_value = None
    if time_match:
        hour = int(time_match.group(1)) % 12
        if time_match.group(3).lower().startswith("p"):
            hour += 12
        time_value = f"{hour:02d}:{time_match.group(2) or '00'}"
    return {"date": iso_date, "time": time_value, "timezone": timezone, "raw": raw.strip()}


def find_date_after(text: str, label: str, window: int = 220, timezone: str = "ET") -> tuple[dict[str, Any], str] | None:
    match = re.search(re.escape(label), text, re.IGNORECASE)
    if not match:
        return None
    fragment = text[match.start() : match.end() + window]
    date_match = DATE_RE.search(fragment)
    if not date_match:
        return None
    raw = fragment[: date_match.end()]
    return normalize_date(date_match, raw, timezone), raw


def find_date_in_html(html: str, label: str, timezone: str = "ET") -> tuple[dict[str, Any], str] | None:
    """Read dates from the same table row or nearby labelled content block.

    This deliberately avoids matching a label in one table cell with the first date
    found elsewhere in flattened page text.
    """
    if BeautifulSoup is None:
        return None
    soup = BeautifulSoup(html, "html.parser")
    label_re = re.compile(re.escape(label), re.IGNORECASE)
    for node in soup.find_all(string=label_re):
        row = node.find_parent("tr")
        if row:
            row_text = row.get_text(" ", strip=True)
            date_match = DATE_RE.search(row_text)
            if date_match:
                return normalize_date(date_match, row_text, timezone), row_text[:600]
        block = node.find_parent(["li", "p", "div", "section", "article"])
        if block:
            block_text = block.get_text(" ", strip=True)
            date_match = DATE_RE.search(block_text)
            if date_match:
                return normalize_date(date_match, block_text, timezone), block_text[:600]
        sibling_text = str(node)
        sibling = node.parent.find_next_sibling() if node.parent else None
        for _ in range(3):
            if not sibling:
                break
            sibling_text += " " + sibling.get_text(" ", strip=True)
            date_match = DATE_RE.search(sibling_text)
            if date_match:
                return normalize_date(date_match, sibling_text, timezone), sibling_text[:600]
            sibling = sibling.find_next_sibling()
    return None


def parse_labelled_dates(source: dict[str, Any], text: str, html: str | None = None) -> ParseResult:
    timezone = source.get("timezone", "ET")
    open_date = None
    for label in source.get("openLabels", []):
        found = find_date_in_html(html, label, timezone) if html else None
        if not found and not source.get("strictHtml", False):
            found = find_date_after(text, label, timezone=timezone)
        if found:
            open_date = found[0]
            break

    deadlines: list[dict[str, Any]] = []
    for label in source.get("deadlineLabels", []):
        found = find_date_in_html(html, label, timezone) if html else None
        if not found and not source.get("strictHtml", False):
            found = find_date_after(text, label, timezone=timezone)
        if found:
            date, raw = found
            deadlines.append({"type": label, **date, "audience": "See official page", "raw": raw})

    if not open_date and not deadlines:
        raise ParseFailure("No configured labelled date could be found")
    excerpt = " | ".join([item["raw"] for item in deadlines] or [open_date["raw"]])[:600]
    status = None
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in source.get("closedMarkers", [])):
        status = "closed"
    return ParseResult(open_date=open_date, deadlines=deadlines or None, status=status, source_text=excerpt)


def parse_closed_marker(source: dict[str, Any], text: str) -> ParseResult:
    lowered = text.lower()
    for marker in source.get("closedMarkers", []):
        if marker.lower() in lowered:
            start = lowered.index(marker.lower())
            return ParseResult(status="closed", source_text=text[max(0, start - 80) : start + 260])
    raise ParseFailure("Configured closed marker not found")


def parse_session_dates(source: dict[str, Any], text: str, html: str | None = None) -> ParseResult:
    timezone = source.get("timezone", "ET")
    deadlines: list[dict[str, Any]] = []
    for label in source.get("deadlineLabels", []):
        found = find_date_in_html(html, label, timezone) if html else None
        if not found and not source.get("strictHtml", False):
            found = find_date_after(text, label, 320, timezone)
        if found:
            date, raw = found
            deadlines.append({"type": label, **date, "audience": "Eligible high school students", "raw": raw})
    if not deadlines:
        raise ParseFailure("No session deadline found")
    return ParseResult(deadlines=deadlines, source_text=" | ".join(item["raw"] for item in deadlines)[:600])


def parse_dartmouth_rounds(source: dict[str, Any], text: str, html: str | None = None) -> ParseResult:
    result = parse_labelled_dates(source, text, html)
    return result


def parse_yygs_status(source: dict[str, Any], text: str) -> ParseResult:
    lowered = text.lower()
    if "application will open soon" in lowered or "application link coming soon" in lowered:
        marker = "application will open soon" if "application will open soon" in lowered else "application link coming soon"
        start = lowered.index(marker)
        return ParseResult(status="upcoming", source_text=text[max(0, start - 80) : start + 330])
    if "apply now" in lowered:
        start = lowered.index("apply now")
        return ParseResult(status="open", source_text=text[max(0, start - 80) : start + 240])
    raise ParseFailure("YYGS application status marker not found")


PARSERS = {
    "labelled_dates": parse_labelled_dates,
    "closed_marker": parse_closed_marker,
    "session_dates": parse_session_dates,
    "dartmouth_rounds": parse_dartmouth_rounds,
    "yygs_status": parse_yygs_status,
}


def derive_status(program: dict[str, Any], today: str) -> str:
    if program.get("status") == "rolling":
        return "rolling"
    deadline_dates = sorted(item["date"] for item in program.get("deadlines", []) if item.get("date"))
    if deadline_dates and deadline_dates[-1] < today:
        return "closed"
    open_date = (program.get("applicationOpenDate") or {}).get("date")
    if open_date and open_date > today:
        return "upcoming"
    if deadline_dates:
        return "open"
    return program.get("status", "unknown")


def validate_candidate(old: dict[str, Any], candidate: ParseResult) -> None:
    if candidate.open_date and candidate.deadlines:
        if any(candidate.open_date["date"] > deadline["date"] for deadline in candidate.deadlines):
            raise ParseFailure("Application open date occurs after a deadline")
    if candidate.deadlines and len(candidate.deadlines) > 8:
        raise ParseFailure("Unexpected number of deadlines")
    old_years = [item["date"][:4] for item in old.get("deadlines", []) if item.get("date")]
    new_years = [item["date"][:4] for item in candidate.deadlines or [] if item.get("date")]
    if old_years and new_years and max(new_years) < min(old_years):
        raise ParseFailure("Unexpected year regression")
    old_deadlines = [item["date"] for item in old.get("deadlines", []) if item.get("date")]
    new_deadlines = [item["date"] for item in candidate.deadlines or [] if item.get("date")]
    if old_deadlines and new_deadlines:
        if len(new_deadlines) < len(old_deadlines) and max(new_years) <= max(old_years):
            raise ParseFailure("Deadline count unexpectedly decreased")
        old_open = (old.get("applicationOpenDate") or {}).get("date")
        if old_open and old_open in new_deadlines and old_open not in old_deadlines:
            raise ParseFailure("A deadline unexpectedly matched the prior opening date")
        if len(old_deadlines) == len(new_deadlines) and max(new_years) == max(old_years):
            shifts = [abs((datetime.fromisoformat(new) - datetime.fromisoformat(old)).days) for old, new in zip(sorted(old_deadlines), sorted(new_deadlines))]
            if any(days > 45 for days in shifts):
                raise ParseFailure("Deadline changed by more than 45 days without an annual rollover")


def load_overrides() -> dict[str, dict[str, Any]]:
    if not OVERRIDES_FILE.exists():
        return {}
    entries = load_json(OVERRIDES_FILE).get("overrides", [])
    return {entry["programId"]: entry for entry in entries}


def apply_override(program: dict[str, Any], override: dict[str, Any], checked_at: str) -> None:
    fields = ("applicationOpenDate", "deadlines", "eligibility", "eligibilityNote", "eligibilitySourceUrl", "status", "sourceUrl", "sourceText")
    for field in fields:
        if field in override:
            program[field] = deepcopy(override[field])
    program["cycleYear"] = override["cycleYear"]
    program["dataOrigin"] = "manual"
    program["verifiedSourceUrl"] = override["verifiedSourceUrl"]
    program["verifiedAt"] = override["verifiedAt"]
    program["lastCheckedAt"] = checked_at
    program["reviewState"] = "verified"
    program.pop("reviewMessage", None)


def conflicts_with_override(program: dict[str, Any], result: ParseResult) -> bool:
    def date_key(value: dict[str, Any] | None) -> tuple[Any, Any, Any] | None:
        return None if not value else (value.get("date"), value.get("time"), value.get("timezone"))

    if result.open_date and date_key(result.open_date) != date_key(program.get("applicationOpenDate")):
        return True
    if result.deadlines:
        candidate = sorted((item.get("type"), *date_key(item)) for item in result.deadlines)
        trusted = sorted((item.get("type"), *date_key(item)) for item in program.get("deadlines", []))
        if candidate != trusted:
            return True
    return bool(result.status and result.status != program.get("status"))


def apply_result(program: dict[str, Any], result: ParseResult, checked_at: str) -> bool:
    before = deepcopy(program)
    if result.open_date:
        program["applicationOpenDate"] = result.open_date
    if result.deadlines:
        program["deadlines"] = result.deadlines
    if result.status:
        program["status"] = result.status
    else:
        program["status"] = derive_status(program, checked_at[:10])
    program["sourceText"] = result.source_text[:600]
    program["lastCheckedAt"] = checked_at
    program["reviewState"] = "verified"
    program["dataOrigin"] = "automatic"
    deadline_years = [item["date"][:4] for item in program.get("deadlines", []) if item.get("date")]
    if deadline_years:
        program["cycleYear"] = int(max(deadline_years))
    program.pop("reviewMessage", None)
    changed = {key: value for key, value in before.items() if key not in {"lastCheckedAt", "lastChangedAt"}} != {
        key: value for key, value in program.items() if key not in {"lastCheckedAt", "lastChangedAt"}
    }
    if changed:
        program["lastChangedAt"] = checked_at
    return changed


def add_review(program: dict[str, Any], source: dict[str, Any], message: str, checked_at: str) -> dict[str, str]:
    program["lastCheckedAt"] = checked_at
    program["reviewState"] = "needs_review"
    program["reviewMessage"] = message
    return {"key": source["id"], "title": f"[review] {source['id']}", "body": f"Source: {source['url']}\n\nCollector did not publish new data.\n\nReason: {message}"}


def run(fetcher=fetch) -> int:
    document = load_json(PROGRAMS_FILE)
    sources = load_json(SOURCES_FILE)
    state = load_json(STATE_FILE)
    programs = {program["id"]: program for program in document["programs"]}
    overrides = load_overrides()
    checked_at = utc_now()
    review_items: list[dict[str, str]] = []
    for program_id, override in overrides.items():
        if program_id in programs:
            apply_override(programs[program_id], override, checked_at)

    for source in sources:
        linked = [programs[program_id] for program_id in source["programIds"]]
        try:
            html = fetcher(source["url"])
            text = clean_text(html)
            parser = PARSERS[source["parser"]]
            result = parser(source, text, html) if source["parser"] in {"labelled_dates", "session_dates", "dartmouth_rounds"} else parser(source, text)
            for program in linked:
                if program["id"] in overrides:
                    if conflicts_with_override(program, result):
                        review_items.append(add_review(program, source, "Automated candidate conflicts with a manual override", checked_at))
                    continue
                validate_candidate(program, result)
                apply_result(program, result, checked_at)
            state[source["id"]] = {"hash": hashlib.sha256(text.encode("utf-8")).hexdigest(), "fetchedAt": checked_at, "url": source["url"]}
        except (requests.RequestException, ParseFailure, KeyError, ValueError) as error:
            for program in linked:
                review_items.append(add_review(program, source, str(error), checked_at))

    document["generatedAt"] = checked_at
    save_json(PROGRAMS_FILE, document)
    save_json(STATE_FILE, state)
    save_json(REVIEW_FILE, review_items)
    print(f"Checked {len(sources)} official sources; {len(review_items)} require review.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
