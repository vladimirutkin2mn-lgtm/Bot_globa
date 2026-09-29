#!/usr/bin/env python3
from __future__ import annotations

import unittest

from fsa_ui_capture import CapturedTemplate


class TemplateTests(unittest.TestCase):
    def test_post_replay(self):
        t = CapturedTemplate(
            registry="CERTIFICATE",
            method="POST",
            url="https://pub.fsa.gov.ru/api/v1/rss/common/certificates/get",
            post_data='{"filter":{"applicant_inn":"5445265650"}}',
        )
        method, url, body = t.render("7701276779", "5445265650")
        self.assertEqual(method, "POST")
        self.assertEqual(body["filter"]["applicant_inn"], "7701276779")
        self.assertIn("certificates/get", url)

    def test_get_replay(self):
        t = CapturedTemplate(
            registry="DECLARATION",
            method="GET",
            url="https://pub.fsa.gov.ru/api/v1/rds/common/declarations?inn=5445265650",
        )
        method, url, body = t.render("7701276779", "5445265650")
        self.assertEqual(method, "GET")
        self.assertIn("7701276779", url)
        self.assertIsNone(body)


if __name__ == "__main__":
    unittest.main()
