import unittest
from pathlib import Path

import vps_audit


class VpsAuditTests(unittest.TestCase):
    def test_parse_meminfo_and_memory_status(self):
        values = vps_audit.parse_meminfo(
            "MemTotal:       1000000 kB\nMemAvailable:   100000 kB\nSwapTotal: 10 kB\n"
        )
        self.assertEqual(values["MemTotal"], 1_024_000_000)
        check = vps_audit.memory_check(values)
        self.assertEqual(check.status, "warning")

    def test_disk_thresholds(self):
        self.assertEqual(vps_audit.disk_check(Path("/"), 100, 79, 21).status, "ok")
        self.assertEqual(vps_audit.disk_check(Path("/"), 100, 80, 20).status, "warning")
        self.assertEqual(vps_audit.disk_check(Path("/"), 100, 92, 8).status, "critical")

    def test_load_is_normalized_by_cpu_count(self):
        self.assertEqual(vps_audit.load_check((3.0, 2.0, 1.0), 4).status, "ok")
        self.assertEqual(vps_audit.load_check((4.0, 2.0, 1.0), 4).status, "warning")

    def test_markdown_contains_all_checks(self):
        report = {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "overall_status": "ok",
            "host": {"hostname": "demo"},
            "checks": [{"name": "memory", "status": "ok", "summary": "50% available"}],
        }
        rendered = vps_audit.render_markdown(report)
        self.assertIn("VPS Health Audit", rendered)
        self.assertIn("50% available", rendered)

    def test_failed_units_are_redacted_by_default(self):
        default = vps_audit.failed_units_check()
        self.assertNotIn("units", default.details)
        self.assertIn("count", default.details)
        opted_in = vps_audit.failed_units_check(show_units=True)
        self.assertIn("units", opted_in.details)

    def test_overall_status_is_deterministic_when_a_check_is_unavailable(self):
        # A real warning must outrank a check that could not run, regardless of the
        # order the checks happen to appear in.
        warning = vps_audit.Check("a", "warning", "", {})
        unavailable = vps_audit.Check("b", "unavailable", "", {})
        for checks in ([warning, unavailable], [unavailable, warning]):
            worst = max(checks, key=lambda check: vps_audit.STATUS_ORDER[check.status])
            self.assertEqual(worst.status, "warning")
        self.assertEqual(len(set(vps_audit.STATUS_ORDER.values())), len(vps_audit.STATUS_ORDER))

    def test_disk_percentage_matches_df(self):
        # 10 GiB total, 1 GiB reserved: df would report 8/(8+1) = 88.9% used.
        gib = 1024 ** 3
        check = vps_audit.disk_check(Path("/"), 10 * gib, 8 * gib, 1 * gib)
        self.assertIn("88.9% used", check.summary)
        self.assertEqual(check.status, "warning")


if __name__ == "__main__":
    unittest.main()
