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


if __name__ == "__main__":
    unittest.main()
