import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collector  # noqa: E402


FIXTURES = Path(__file__).parent / "fixtures"


class CollectorTests(unittest.TestCase):
    def test_normalize_date_and_time(self):
        match = collector.DATE_RE.search("Deadline: May 14, 2026 at 11:59 p.m. ET")
        result = collector.normalize_date(match, "Deadline: May 14, 2026 at 11:59 p.m. ET")
        self.assertEqual(result["date"], "2026-05-14")
        self.assertEqual(result["time"], "23:59")
        self.assertEqual(result["timezone"], "ET")

    def test_labelled_dates_extract_open_and_deadline(self):
        text = collector.clean_text((FIXTURES / "brown.html").read_text(encoding="utf-8"))
        result = collector.parse_labelled_dates({"openLabels": ["Application Opens"], "deadlineLabels": ["Application Deadline"]}, text)
        self.assertEqual(result.open_date["date"], "2026-01-14")
        self.assertEqual(result.deadlines[0]["date"], "2026-05-15")

    def test_closed_marker_preserves_unknown_dates(self):
        text = collector.clean_text((FIXTURES / "closed.html").read_text(encoding="utf-8"))
        result = collector.parse_closed_marker({"closedMarkers": ["program is closed"]}, text)
        self.assertEqual(result.status, "closed")
        self.assertIsNone(result.deadlines)

    def test_yygs_open_soon_status(self):
        result = collector.parse_yygs_status({}, "YYGS application will open soon. We anticipate that the application will open by the end of September.")
        self.assertEqual(result.status, "upcoming")

    def test_rejects_open_after_deadline(self):
        old = {"deadlines": [{"date": "2026-05-15"}]}
        candidate = collector.ParseResult(
            open_date={"date": "2026-06-01", "time": None, "timezone": "ET", "raw": "June 1, 2026"},
            deadlines=[{"date": "2026-05-15", "time": None, "timezone": "ET", "raw": "May 15, 2026"}],
        )
        with self.assertRaises(collector.ParseFailure):
            collector.validate_candidate(old, candidate)

    def test_status_calculation(self):
        self.assertEqual(collector.derive_status({"deadlines": [{"date": "2026-05-01"}]}, "2026-08-30"), "closed")
        self.assertEqual(collector.derive_status({"applicationOpenDate": {"date": "2027-01-01"}, "deadlines": [{"date": "2027-05-01"}]}, "2026-08-30"), "upcoming")

    def test_table_parser_keeps_label_and_date_in_the_same_row(self):
        html = (FIXTURES / "cornell-table.html").read_text(encoding="utf-8")
        text = collector.clean_text(html)
        result = collector.parse_labelled_dates(
            {"openLabels": ["Applications Open"], "deadlineLabels": ["Application form due"], "strictHtml": True}, text, html
        )
        self.assertEqual(result.open_date["date"], "2026-01-12")
        self.assertEqual(result.deadlines[0]["date"], "2026-05-14")

    def test_stanford_sources_are_independent(self):
        summer_html = (FIXTURES / "stanford-summer-institutes.html").read_text(encoding="utf-8")
        humanities_html = (FIXTURES / "stanford-humanities.html").read_text(encoding="utf-8")
        source = {"openLabels": [], "deadlineLabels": ["Application Deadline"], "closedMarkers": ["application is currently closed"], "timezone": "PT", "strictHtml": True}
        summer = collector.parse_labelled_dates(source, collector.clean_text(summer_html), summer_html)
        humanities = collector.parse_labelled_dates(source, collector.clean_text(humanities_html), humanities_html)
        self.assertEqual(summer.deadlines[0]["date"], "2026-03-13")
        self.assertEqual(humanities.deadlines[0]["date"], "2026-02-02")
        self.assertEqual(humanities.deadlines[0]["timezone"], "PT")
        self.assertEqual(summer.status, "closed")
        self.assertEqual(humanities.status, "closed")

    def test_manual_override_is_not_replaced_by_candidate(self):
        program = {"id": "test", "deadlines": [{"type": "Application Deadline", "date": "2026-02-02", "time": "23:59", "timezone": "PT"}]}
        override = {"programId": "test", "cycleYear": 2026, "deadlines": program["deadlines"], "status": "closed", "verifiedSourceUrl": "https://example.edu", "verifiedAt": "2026-08-30T00:00:00Z"}
        collector.apply_override(program, override, "2026-08-30T01:00:00Z")
        candidate = collector.ParseResult(deadlines=[{"type": "Application Deadline", "date": "2026-03-13", "time": "23:59", "timezone": "PT"}])
        self.assertTrue(collector.conflicts_with_override(program, candidate))
        self.assertEqual(program["deadlines"][0]["date"], "2026-02-02")

    def test_rejects_deadline_count_decrease(self):
        old = {"deadlines": [{"date": "2026-04-28"}, {"date": "2026-05-14"}]}
        candidate = collector.ParseResult(deadlines=[{"date": "2026-05-14", "time": None, "timezone": "ET", "raw": "May 14, 2026"}])
        with self.assertRaises(collector.ParseFailure):
            collector.validate_candidate(old, candidate)


if __name__ == "__main__":
    unittest.main()
