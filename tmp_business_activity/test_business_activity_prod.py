#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import business_activity_prod as p


class ProdTests(unittest.TestCase):
    def test_normalize_and_dedupe(self):
        self.assertEqual(p.normalize_inn("54-45 265650"), "5445265650")
        self.assertEqual(p.normalize_inn("5445265650.0"), "5445265650")
        self.assertEqual(p.normalize_inn("abc"), "")
        self.assertEqual(
            p.dedupe_keep_order(["5445265650", "5445265650", "7701276779"], 10),
            ["5445265650", "7701276779"],
        )

    def test_evidence_class(self):
        self.assertEqual(p.evidence_class({"status":"FOUND","same_as_applicant_docs":2,"other_manufacturer_docs":0}), "PRODUCTION_STRONG")
        self.assertEqual(p.evidence_class({"status":"FOUND","same_as_applicant_docs":0,"other_manufacturer_docs":3}), "TRADE_IMPORT_STRONG")
        self.assertEqual(p.evidence_class({"status":"FOUND","same_as_applicant_docs":1,"other_manufacturer_docs":1}), "MIXED_PRODUCTION_AND_TRADE")
        self.assertEqual(p.evidence_class({"status":"NOT_FOUND"}), "NO_CERT_EVIDENCE")

    def test_csv_input(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.csv"
            path.write_text("ИНН текстом;name\n5445265650;A\n7701276779;B\n5445265650;C\n", encoding="utf-8-sig")
            self.assertEqual(p.load_inns(path, "финал", "ИНН текстом", 5000), ["5445265650", "7701276779"])

    def test_minimal_xlsx_input(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.xlsx"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("xl/workbook.xml", '''<?xml version="1.0" encoding="UTF-8"?>
                <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <sheets><sheet name="финал" sheetId="1" r:id="rId1"/></sheets>
                </workbook>''')
                z.writestr("xl/_rels/workbook.xml.rels", '''<?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                  <Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/>
                </Relationships>''')
                z.writestr("xl/sharedStrings.xml", '''<?xml version="1.0" encoding="UTF-8"?>
                <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="3" uniqueCount="3">
                  <si><t>ИНН текстом</t></si><si><t>5445265650</t></si><si><t>7701276779</t></si>
                </sst>''')
                z.writestr("xl/worksheets/sheet1.xml", '''<?xml version="1.0" encoding="UTF-8"?>
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
                  <row r="1"><c r="A1" t="s"><v>0</v></c></row>
                  <row r="2"><c r="A2" t="s"><v>1</v></c></row>
                  <row r="3"><c r="A3" t="s"><v>2</v></c></row>
                </sheetData></worksheet>''')
            self.assertEqual(p.load_inns(path, "финал", "ИНН текстом", 5000), ["5445265650", "7701276779"])

    def test_state_resume_and_export(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            db = p.StateDB(out / "checkpoint.sqlite3")
            db.seed(["5445265650", "7701276779"])
            db.finish(
                "5445265650",
                {"status":"FOUND","source":"S34","documents":2,"same_as_applicant_docs":2,"other_manufacturer_docs":0,"products":["упаковка"],"urls":["https://s-34.ru/x"]},
                None,
                "FOUND",
            )
            self.assertEqual(db.pending(), ["7701276779"])
            p.export_snapshots(db, out)
            summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["found"], 1)
            self.assertEqual(summary["pending"], 1)
            db.close()


if __name__ == "__main__":
    unittest.main()
