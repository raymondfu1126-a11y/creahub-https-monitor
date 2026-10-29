import unittest
from unittest.mock import patch

import monitor


class MonitoringBehavior(unittest.TestCase):
    def test_expiry_warning_and_critical_boundaries(self):
        for days, severity in [(8, 0), (7, 1), (1.01, 1), (1, 2), (-1, 2)]:
            with self.subTest(days=days):
                self.assertEqual(monitor.expiry_severity(days * 86400), severity)

    def test_healthy_checks_are_quiet(self):
        state, alerts = monitor.transition({}, [{"kind": "tls", "target": "creahub.art"}], "2026-10-29")
        self.assertEqual(alerts, [])
        self.assertEqual(state["active"], {})

    def test_new_persistent_escalated_and_recurrent_anomalies(self):
        warning = {"kind": "tls", "target": "creahub.art", "issue": "certificate_expiring", "severity": 1}
        state, alerts = monitor.transition({}, [warning], "2026-10-29")
        self.assertEqual(len(alerts), 1)
        state, alerts = monitor.transition(state, [warning], "2026-10-30")
        self.assertEqual(alerts, [])
        state, alerts = monitor.transition(state, [dict(warning, severity=2)], "2026-10-31")
        self.assertEqual(len(alerts), 1)
        state, alerts = monitor.transition(state, [warning], "2026-11-01")
        self.assertEqual(alerts, [])
        state, alerts = monitor.transition(state, [], "2026-11-02")
        self.assertEqual(alerts, [])
        state, alerts = monitor.transition(state, [warning], "2026-11-03")
        self.assertEqual(len(alerts), 1)

    def test_http_200_does_not_hide_unhealthy_payload(self):
        url = "https://creahub.art/api/health"
        result = monitor.evaluate_http(url, "200", url, "0", '{"status":"error"}')
        self.assertEqual(result["issue"], "health_not_ok")
        result = monitor.evaluate_http(url, "200", url, "0", '{"status":"ok"}')
        self.assertNotIn("issue", result)

    def test_redirect_must_reach_canonical_login(self):
        url = "https://www.creahub.art/"
        result = monitor.evaluate_http(url, "200", "https://creahub.art/login", "0", "")
        self.assertNotIn("issue", result)
        result = monitor.evaluate_http(url, "200", "https://example.com/login", "0", "")
        self.assertEqual(result["issue"], "unexpected_redirect")

    def test_invalid_tls_result_is_anomaly(self):
        result = monitor.evaluate_http("https://creahub.art/login", "200", "https://creahub.art/login", "60", "")
        self.assertEqual(result["issue"], "http_or_tls_failure")

    def test_transient_failure_recovery_is_quiet(self):
        healthy = {"kind": "http", "target": "https://creahub.art/login"}
        with patch.object(monitor, "http_check", side_effect=[TimeoutError("temporary"), healthy]):
            result = monitor.check_with_retry("http", healthy["target"], delay=0)
        self.assertEqual(result["attempts"], 2)
        self.assertNotIn("issue", result)

    def test_failure_requires_second_failed_probe(self):
        with patch.object(monitor, "tls_check", side_effect=TimeoutError("unreachable")) as call:
            result = monitor.check_with_retry("tls", "creahub.art", delay=0)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(result["issue"], "probe_failed")


if __name__ == "__main__":
    unittest.main()
