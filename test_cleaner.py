import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from csv_cleaner import clean_csv


class CleanerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_csv(self, text, config=None, **kwargs):
        source = self.root / "input.csv"
        source.write_text(text, encoding="utf-8")
        return clean_csv(source, self.root / "output", config, **kwargs)

    def read(self, name):
        return pd.read_csv(self.root / "output" / name, dtype=str, keep_default_na=False)

    def test_normalization_and_duplicate_removal_preserve_ids(self):
        report = self.run_csv(" Customer ID ,Email\n001, user@EXAMPLE.COM \n001,user@example.com\n")
        self.assertEqual(report["duplicate_rows_removed"], 1)
        self.assertEqual(self.read("cleaned.csv").iloc[0].to_dict(), {"customer_id": "001", "email": "user@example.com"})
        self.assertIn("duplicate_row", self.read("issues.csv")["issue"].tolist())

    def test_invalid_email_is_retained_and_reported(self):
        report = self.run_csv("email\nbad..name@example.com\nwrong-address\n")
        self.assertEqual(report["rows_with_validation_errors"], 2)
        self.assertEqual(self.read("cleaned.csv")["email"].tolist(), ["bad..name@example.com", "wrong-address"])
        self.assertEqual(self.read("rejected.csv")["source_record"].tolist(), ["2", "3"])

    def test_missing_optional_vs_required(self):
        report = self.run_csv("name,note\nNULL,N/A\n", {"columns": {"name": {"required": True}}})
        self.assertEqual(report["missing_cells"], 2)
        self.assertEqual(report["rows_with_validation_errors"], 1)
        self.assertEqual(self.read("cleaned.csv").iloc[0].tolist(), ["", ""])

    def test_dates_ranges_and_choices(self):
        rules = {"columns": {"age": {"type": "integer", "min": 0, "max": 120}, "date": {"type": "date", "formats": ["%d/%m/%Y"]}, "status": {"choices": ["active"]}}}
        report = self.run_csv("age,date,status\n23,01/10/2026,active\n-1,30/02/2026,unknown\n2.5,02/10/2026,active\n", rules)
        self.assertEqual(self.read("cleaned.csv").iloc[0]["date"], "2026-10-01")
        self.assertEqual(report["rows_with_validation_errors"], 2)
        self.assertEqual(set(report["issues_by_type"]), {"formatting", "below_minimum", "invalid_date", "invalid_choice", "invalid_integer"})

    def test_header_collision_is_rejected_without_outputs(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            self.run_csv("Full Name,full_name\nA,B\n")
        self.assertFalse((self.root / "output").exists())

    def test_malformed_record_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "expected 2"):
            self.run_csv("id,name\n1,A,extra\n")

    def test_empty_and_header_only(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            self.run_csv("")
        report = self.run_csv("id,email\n")
        self.assertEqual(report["output_rows"], 0)
        self.assertEqual(len(self.read("issues.csv")), 0)

    def test_existing_output_is_protected(self):
        self.run_csv("id\n001\n")
        with self.assertRaisesRegex(ValueError, "empty"):
            self.run_csv("id\n002\n")
        self.assertEqual(self.read("cleaned.csv").iloc[0]["id"], "001")

    def test_config_typo_is_reported(self):
        with self.assertRaisesRegex(ValueError, "not present"):
            self.run_csv("id\n1\n", {"columns": {"ids": {"required": True}}})

    def test_nonfinite_numbers_are_invalid(self):
        report = self.run_csv("score\nInfinity\n-Inf\n", {"columns": {"score": {"type": "number"}}})
        self.assertEqual(report["rows_with_validation_errors"], 2)

    def test_quoted_newlines_and_delimiter(self):
        report = self.run_csv('id;note\n001;"hello\nworld"\n001;"hello\nworld"\n', delimiter=";")
        self.assertEqual(report["duplicate_rows_removed"], 1)
        self.assertEqual(self.read("cleaned.csv").iloc[0]["note"], "hello\nworld")
        self.assertEqual(self.read("issues.csv").iloc[0]["source_record"], "3")

    def test_duplicate_retention_can_be_configured(self):
        report = self.run_csv("id\n1\n1\n", {"drop_duplicates": False})
        self.assertEqual(report["duplicate_rows_detected"], 1)
        self.assertEqual(report["output_rows"], 2)

    def test_custom_missing_tokens_preserve_literal_na(self):
        report = self.run_csv("code\nNA\nNULL\n", {"missing_tokens": [""]})
        self.assertEqual(report["missing_cells"], 0)
        self.assertEqual(self.read("cleaned.csv")["code"].tolist(), ["NA", "NULL"])

    def test_rejected_source_column_does_not_overwrite_user_data(self):
        self.run_csv("source_record,email\noriginal,bad\n")
        rejected = self.read("rejected.csv")
        self.assertEqual(rejected.iloc[0]["source_record"], "original")
        self.assertEqual(rejected.iloc[0]["_source_record"], "2")

    def test_cli_exit_codes_and_export(self):
        source = self.root / "input.csv"
        source.write_text("email\nbad\n", encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "csv_cleaner", str(source), "--output", str(self.root / "cli"), "--fail-on-errors"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        summary = json.loads((self.root / "cli" / "summary.json").read_text())
        self.assertEqual(summary["output_rows_with_validation_errors"], 1)


if __name__ == "__main__":
    unittest.main()
