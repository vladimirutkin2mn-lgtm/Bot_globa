#!/usr/bin/env python3
from __future__ import annotations

import unittest

from fsa import (
    CERT_LIST,
    DECL_LIST,
    FSAClient,
    SourceUnavailable,
    STATUS_FOUND,
    STATUS_UNAVAILABLE,
    aggregate_search,
)

TARGET = "7701276779"


class FakeClient(FSAClient):
    def __init__(self):
        super().__init__()
        self._bootstrapped = True

    def _post(self, url, payload):
        if url == CERT_LIST:
            return {"total": 1, "items": [{"id": 101, "number": "CERT-101", "endDate": "2099-12-31"}]}
        if url == DECL_LIST:
            return {"total": 1, "items": [{"id": 202, "number": "DECL-202", "declEndDate": "2099-12-31"}]}
        raise AssertionError(url)

    def _get(self, url):
        if url.endswith("/101"):
            return {
                "number": "CERT-101",
                "date": "2026-01-01",
                "endDate": "2099-12-31",
                "manufacturer": {"inn": TARGET, "fullName": "Target Manufacturer"},
                "applicant": {"inn": "7712345678", "fullName": "Other Applicant"},
                "product": {"fullName": "Packaging material"},
            }
        if url.endswith("/202"):
            return {
                "number": "DECL-202",
                "declDate": "2026-02-01",
                "declEndDate": "2099-12-31",
                "manufacturer": {"inn": "7723456789", "fullName": "Other Manufacturer"},
                "applicant": {"inn": TARGET, "fullName": "Target Applicant"},
                "product": {"fullName": "Industrial goods"},
            }
        raise AssertionError(url)


class BlockedClient(FSAClient):
    def __init__(self):
        super().__init__()
        self._bootstrapped = True

    def _post(self, url, payload):
        raise SourceUnavailable("HTTP 403")


class FsaTests(unittest.TestCase):
    def test_role_split_and_aggregation(self):
        result = FakeClient().search_inn(TARGET)
        self.assertEqual(result["status"], STATUS_FOUND)
        row = aggregate_search(result)
        self.assertEqual(row["ФСА документы всего"], 2)
        self.assertEqual(row["ФСА сертификаты"], 1)
        self.assertEqual(row["ФСА декларации"], 1)
        self.assertEqual(row["ФСА manufacturer"], 1)
        self.assertEqual(row["ФСА applicant"], 1)
        self.assertEqual(row["ФСА действующие"], 2)
        self.assertIn("Packaging material", row["ФСА продукция"])
        self.assertIn("Industrial goods", row["ФСА продукция"])

    def test_source_block_is_not_not_found(self):
        result = BlockedClient().search_inn(TARGET)
        self.assertEqual(result["status"], STATUS_UNAVAILABLE)
        self.assertIn("403", result["source_error"])

    def test_invalid_inn_rejected(self):
        with self.assertRaises(ValueError):
            FakeClient().search_inn("123")


if __name__ == "__main__":
    unittest.main()
