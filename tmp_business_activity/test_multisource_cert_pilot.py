#!/usr/bin/env python3
from __future__ import annotations

import unittest
from multisource_cert_pilot import clean_inn, exact_inn_role_from_text, product_excerpt


class PilotTests(unittest.TestCase):
    def test_clean_inn(self):
        self.assertEqual(clean_inn("77-28 311156"), "7728311156")

    def test_applicant_role(self):
        t = "Заявитель\nООО ТЕСТ\nИНН\n7728311156\nИзготовитель\nABC"
        self.assertEqual(exact_inn_role_from_text(t, "7728311156"), {"APPLICANT"})

    def test_manufacturer_role(self):
        t = "Заявитель\nООО X\nИзготовитель\nООО ТЕСТ\nИНН\n7728311156\nПродукция\nСтанок"
        self.assertEqual(exact_inn_role_from_text(t, "7728311156"), {"MANUFACTURER"})

    def test_product_excerpt(self):
        self.assertIn("Станок", product_excerpt("Заявитель X\nПродукция\nСтанок токарный"))


if __name__ == "__main__":
    unittest.main()
