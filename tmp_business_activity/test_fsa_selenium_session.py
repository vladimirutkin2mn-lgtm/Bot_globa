#!/usr/bin/env python3
from __future__ import annotations

import unittest

from fsa_selenium_session import _candidate_auth_from_storage, _safe_headers


class SeleniumSessionTests(unittest.TestCase):
    def test_extract_jwt_from_storage(self):
        storage = {
            "local": {"auth": '{"accessToken":"aaaabbbbb.cccccddddd.eeeeefffff"}'},
            "session": {},
        }
        auth = _candidate_auth_from_storage(storage)
        self.assertEqual(auth, "Bearer aaaabbbbb.cccccddddd.eeeeefffff")

    def test_keep_only_replay_headers(self):
        got = _safe_headers({
            "Authorization": "Bearer abc",
            "lkId": "1",
            "Cookie": "secret=1",
            "User-Agent": "x",
        })
        self.assertEqual(got["Authorization"], "Bearer abc")
        self.assertEqual(got["lkId"], "1")
        self.assertNotIn("Cookie", got)
        self.assertNotIn("User-Agent", got)


if __name__ == "__main__":
    unittest.main()
