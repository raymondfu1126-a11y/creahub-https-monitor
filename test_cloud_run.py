import base64
import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

import cloud_run


class CloudAlertBehavior(unittest.TestCase):
    def call_run(self, previous, checks, request_effect=None):
        stored = {"sha": "state-blob", "content": base64.b64encode(json.dumps(previous).encode()).decode()}
        result = {"checked_at_utc": "2026-10-29T08:00:00Z", "status": "attention" if checks else "ok", "checks": checks}
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "example/monitor"}, clear=True), \
             patch.object(cloud_run, "run_checks", return_value=result), \
             patch.object(cloud_run, "github_request", side_effect=request_effect or [stored, {}]) as api, \
             contextlib.redirect_stdout(io.StringIO()):
            code = cloud_run.main()
        return code, api.call_args_list

    def test_new_anomaly_persists_before_triggering_failure_email(self):
        previous = {"schema_version": 1, "last_check_date_utc": "2026-10-29", "active": {}}
        check = {"kind": "tls", "target": "creahub.art", "issue": "probe_failed", "severity": 2}
        code, calls = self.call_run(previous, [check])
        self.assertEqual(code, 1)
        self.assertEqual([c.args[0] for c in calls], ["GET", "PUT"])
        saved = json.loads(base64.b64decode(calls[1].args[2]["content"]))
        self.assertEqual(saved["active"], {"tls|creahub.art|probe_failed": 2})

    def test_same_anomaly_has_no_write_and_no_email(self):
        previous = {"schema_version": 1, "last_check_date_utc": "2026-10-29",
                    "active": {"tls|creahub.art|probe_failed": 2}}
        check = {"kind": "tls", "target": "creahub.art", "issue": "probe_failed", "severity": 2}
        code, calls = self.call_run(previous, [check])
        self.assertEqual(code, 0)
        self.assertEqual([c.args[0] for c in calls], ["GET"])

    def test_recovery_clears_state_without_email(self):
        previous = {"schema_version": 1, "last_check_date_utc": "2026-10-29",
                    "active": {"tls|creahub.art|probe_failed": 2}}
        code, calls = self.call_run(previous, [])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(base64.b64decode(calls[1].args[2]["content"]))["active"], {})

    def test_failed_state_write_is_not_reported_as_healthy(self):
        previous = {"schema_version": 1, "last_check_date_utc": "2026-10-28", "active": {}}
        stored = {"sha": "state-blob", "content": base64.b64encode(json.dumps(previous).encode()).decode()}
        with self.assertRaisesRegex(RuntimeError, "state unavailable"):
            self.call_run(previous, [], [stored, RuntimeError("state unavailable")])


if __name__ == "__main__":
    unittest.main()
