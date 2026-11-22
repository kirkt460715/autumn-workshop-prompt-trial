import csv
from pathlib import Path
import unittest

DATA = Path(__file__).resolve().parents[1] / "data"

TABLES = {
    'classes': ('class_id pair school day assigned actual teacher group_type', 'class_id'),
    'children': ('class_id child family grade attendance overtime', 'class_id child'),
    'answers': ('answer_id class_id child day source setting raw_score max_score independent', 'answer_id'),
    'contacts': ('contact source_class target_class day kind content', 'contact'),
    'review_plan': ('review day use target gain_floor missing_gap_ceiling burden_ceiling min_pairs', 'review'),
    'next_classes': ('candidate day school grade teacher block prior_material state paired_with followup_slot', 'candidate'),
}


class SourceDataTests(unittest.TestCase):
    def load(self, name):
        fields, _ = TABLES[name]
        with (DATA / (name + ".csv")).open(encoding="utf-8", newline="") as handle:
            contents = csv.DictReader(handle)
            self.assertEqual(contents.fieldnames, fields.split())
            records = list(contents)
        self.assertTrue(records)
        self.assertTrue(all(None not in row and None not in row.values() for row in records))
        return records

    def test_format_and_record_keys(self):
        for name, (_, key) in TABLES.items():
            with self.subTest(table=name):
                records = self.load(name)
                values = [tuple(row[field] for field in key.split()) for row in records]
                self.assertTrue(all(all(value) for value in values))
                self.assertEqual(len(values), len(set(values)))

    def test_related_source_records(self):
        rows = {name: self.load(name) for name in TABLES}
        arms = {}
        for record in rows["classes"]:
            arms.setdefault(record["pair"], set()).add(record["assigned"])
        self.assertTrue(all(arm == {"control", "hint"} for arm in arms.values()))
        self.assertTrue(any(r["setting"] == "home" for r in rows["answers"]))
        self.assertTrue(any(r["raw_score"] == "0" and r["source"] == "transfer" for r in rows["answers"]))
        self.assertEqual({"exploratory", "formal"}, {r["use"] for r in rows["review_plan"]})
        self.assertTrue(any(r["actual"] != r["assigned"] for r in rows["classes"]))
        self.assertLess(len({r["followup_slot"] for r in rows["next_classes"]}), len(rows["next_classes"]))
