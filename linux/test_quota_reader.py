# SPDX-License-Identifier: GPL-3.0-only
"""Offline protocol and parser checks; no Codex account requests are sent."""

import json
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

import quota_reader


class ShapeTests(unittest.TestCase):
    def test_named_codex_bucket_wins_and_windows_use_duration(self):
        raw = {
            "rateLimits": {"primary": {"usedPercent": 99, "windowDurationMins": 300}},
            "rateLimitsByLimitId": {
                "other": {"primary": {"usedPercent": 1, "windowDurationMins": 300}},
                "codex": {
                    "primary": {"usedPercent": 31, "windowDurationMins": 10080, "resetsAt": 2000},
                    "secondary": {"usedPercent": 42.5, "windowDurationMins": 300, "resetsAt": 1000},
                },
            },
        }
        self.assertEqual(quota_reader._shape_quota(raw, 10), {
            "fetched_at": 10,
            "five_hour": {"remaining": 57.5, "resets_at": 1000},
            "weekly": {"remaining": 69.0, "resets_at": 2000},
        })

    def test_missing_and_invalid_values_are_unknown(self):
        for used in (None, "12", True, float("nan"), float("inf")):
            with self.subTest(used=used):
                result = quota_reader._shape_quota({"rateLimits": {
                    "primary": {"usedPercent": used, "windowDurationMins": 300, "resetsAt": "123"},
                    "secondary": {"usedPercent": 4},
                }})
                self.assertEqual(result["five_hour"], {"remaining": None, "resets_at": None})
                self.assertEqual(result["weekly"], {"remaining": None, "resets_at": None})

    def test_remaining_percentage_is_clamped(self):
        for used, expected in ((-10, 100), (120, 0), (100, 0), (0, 100)):
            result = quota_reader._shape_quota({"primary": {
                "usedPercent": used, "windowDurationMins": 300,
            }})
            self.assertEqual(result["five_hour"]["remaining"], expected)

    def test_empty_data_does_not_mean_full_quota(self):
        result = quota_reader._shape_quota({})
        self.assertIsNone(result["five_hour"]["remaining"])
        self.assertIsNone(result["weekly"]["remaining"])

    def test_multiple_unrelated_buckets_are_not_guessed(self):
        result = quota_reader._shape_quota({"rateLimitsByLimitId": {
            "first": {"primary": {"usedPercent": 0, "windowDurationMins": 300}},
            "second": {"primary": {"usedPercent": 0, "windowDurationMins": 300}},
        }})
        self.assertIsNone(result["five_hour"]["remaining"])

    def test_single_unrelated_bucket_is_not_displayed_as_codex(self):
        result = quota_reader._shape_quota({"rateLimitsByLimitId": {
            "code_review": {
                "primary": {"usedPercent": 20, "windowDurationMins": 300},
                "secondary": {"usedPercent": 40, "windowDurationMins": 10080},
            },
        }})
        self.assertIsNone(result["five_hour"]["remaining"])
        self.assertIsNone(result["weekly"]["remaining"])

    def test_invalid_result_is_rejected(self):
        for raw in (None, [], "secret-token"):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError) as caught:
                quota_reader._shape_quota(raw)
            self.assertNotIn("secret", str(caught.exception))


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        resolver = mock.patch.object(
            quota_reader, "resolve_codex_binary", return_value="/fake/codex"
        )
        self.resolve_binary = resolver.start()
        self.addCleanup(resolver.stop)

    def spawn_fake(self, script):
        original = subprocess.Popen
        children = []

        def spawn(command, **kwargs):
            self.assertEqual(command, ["/fake/codex", "app-server"])
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
            child = original([sys.executable, "-u", "-c", script], **kwargs)
            children.append(child)
            return child

        return mock.patch.object(quota_reader.subprocess, "Popen", side_effect=spawn), children

    def test_handshake_notifications_partial_lines_and_cleanup(self):
        script = '''
import json, sys, time
def receive(): return json.loads(sys.stdin.readline())
first = receive()
assert first["method"] == "initialize" and first["id"] == 1
assert first["params"]["clientInfo"] == {"name": "codex-quota-float", "title": "Codex Quota Float", "version": "0.2.0"}
sys.stdout.write('not json\\n{"method":"server/notification"}\\n')
sys.stdout.write('{"id":1,"res')
sys.stdout.flush()
time.sleep(0.03)
sys.stdout.write('ult":{}}\\n')
sys.stdout.flush()
second = receive()
assert second["method"] == "initialized" and "id" not in second
third = receive()
assert third["method"] == "account/rateLimits/read" and third["id"] == 2
print(json.dumps({"id":2,"result":{"rateLimits":{"primary":{"usedPercent":25,"windowDurationMins":300,"resetsAt":1234}}}}), flush=True)
time.sleep(60)
'''
        patch, children = self.spawn_fake(script)
        with patch:
            result = quota_reader.read_quota(2)
        self.assertEqual(result["five_hour"], {"remaining": 75.0, "resets_at": 1234})
        self.assertIsNone(result["weekly"]["remaining"])
        self.assertIsInstance(result["fetched_at"], float)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdin.closed)
        self.assertTrue(children[0].stdout.closed)

    def test_account_error_does_not_expose_remote_error_or_stderr(self):
        script = '''
import json, sys
json.loads(sys.stdin.readline())
print('{"id":1,"result":{}}', flush=True)
json.loads(sys.stdin.readline())
json.loads(sys.stdin.readline())
print('Bearer private-credential', file=sys.stderr, flush=True)
print('{"id":2,"error":{"message":"private-credential"}}', flush=True)
'''
        patch, children = self.spawn_fake(script)
        with patch, self.assertRaisesRegex(RuntimeError, "无法读取账户额度") as caught:
            quota_reader.read_quota(2)
        self.assertNotIn("private-credential", str(caught.exception))
        self.assertIsNotNone(children[0].poll())

    def test_initialization_error_is_safe_and_reaped(self):
        patch, children = self.spawn_fake('import sys; sys.stdin.readline(); print(\'{"id":1,"error":{"message":"private-credential"}}\', flush=True)')
        with patch, self.assertRaisesRegex(RuntimeError, "初始化失败") as caught:
            quota_reader.read_quota(2)
        self.assertNotIn("private-credential", str(caught.exception))
        self.assertIsNotNone(children[0].poll())

    def test_early_exit_is_reported_without_waiting_for_timeout(self):
        patch, children = self.spawn_fake("import sys; sys.stdin.readline(); sys.exit(3)")
        started = time.monotonic()
        with patch, self.assertRaisesRegex(RuntimeError, "提前结束"):
            quota_reader.read_quota(5)
        self.assertLess(time.monotonic() - started, 2)
        self.assertIsNotNone(children[0].poll())

    def test_timeout_kills_and_reaps_server_that_ignores_terminate(self):
        patch, children = self.spawn_fake("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)")
        started = time.monotonic()
        with patch, self.assertRaisesRegex(RuntimeError, "超时"):
            quota_reader.read_quota(0.15)
        self.assertLess(time.monotonic() - started, 2)
        self.assertIsNotNone(children[0].poll())

    def test_cancellation_stops_and_reaps_the_server(self):
        patch, children = self.spawn_fake("import time; time.sleep(60)")
        event = threading.Event()
        timer = threading.Timer(0.1, event.set)
        started = time.monotonic()
        timer.start()
        try:
            with patch, self.assertRaisesRegex(RuntimeError, "已取消"):
                quota_reader.read_quota(5, cancel_event=event)
        finally:
            timer.cancel()
        self.assertLess(time.monotonic() - started, 2)
        self.assertIsNotNone(children[0].poll())

    def test_cancelled_before_start_does_not_spawn(self):
        event = threading.Event()
        event.set()
        with mock.patch.object(quota_reader.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "已取消"):
                quota_reader.read_quota(cancel_event=event)
            spawn.assert_not_called()
        self.resolve_binary.assert_not_called()

    def test_invalid_config_does_not_spawn(self):
        self.resolve_binary.side_effect = RuntimeError("CODEX_BIN 配置无效。")
        with mock.patch.object(quota_reader.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "CODEX_BIN 配置无效"):
                quota_reader.read_quota()
            spawn.assert_not_called()

    def test_spawn_error_has_no_sensitive_details(self):
        with mock.patch.object(quota_reader.subprocess, "Popen", side_effect=OSError("private-credential")):
            with self.assertRaisesRegex(RuntimeError, "无法启动") as caught:
                quota_reader.read_quota()
        self.assertNotIn("private-credential", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
