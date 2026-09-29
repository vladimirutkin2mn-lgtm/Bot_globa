#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest

from fsa_browser_client import BrowserFSAClient
from fsa import SourceUnavailable


class FakeDriver:
    def __init__(self, result):
        self.result = result
        self.timeout = None

    def set_script_timeout(self, value):
        self.timeout = value

    def execute_async_script(self, script, method, url, payload, headers):
        return self.result

    def quit(self):
        pass


class BrowserClientTests(unittest.TestCase):
    def test_json_response(self):
        d = FakeDriver({"ok": True, "status": 200, "text": json.dumps({"items": []})})
        c = BrowserFSAClient(d, {"Authorization": "Bearer abc"})
        got = c._post("https://pub.fsa.gov.ru/api/v1/test", {"x": 1})
        self.assertEqual(got, {"items": []})
        self.assertEqual(d.timeout, 120)

    def test_block_status(self):
        d = FakeDriver({"ok": True, "status": 403, "text": ""})
        c = BrowserFSAClient(d, {})
        with self.assertRaises(SourceUnavailable):
            c._get("https://pub.fsa.gov.ru/api/v1/test")

    def test_fetch_error(self):
        d = FakeDriver({"ok": False, "error": "TypeError: Failed to fetch"})
        c = BrowserFSAClient(d, {})
        with self.assertRaises(SourceUnavailable):
            c._get("https://pub.fsa.gov.ru/api/v1/test")


if __name__ == "__main__":
    unittest.main()
