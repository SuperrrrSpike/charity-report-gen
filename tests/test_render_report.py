from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from render_report import render_donor, render_schema, render_standard, validate_case


class RenderReportTests(unittest.TestCase):
    def test_user_visible_sources_have_no_replacement_characters(self):
        paths = [*(ROOT / "mock").glob("*.json"), ROOT / "docs/PRD.md"]
        for path in paths:
            self.assertNotIn("\ufffd", path.read_text(encoding="utf-8"), str(path))

    @classmethod
    def setUpClass(cls):
        cls.case = json.loads((ROOT / "mock/spark-library.json").read_text(encoding="utf-8"))

    def test_all_mock_cases_are_valid(self):
        for path in (ROOT / "mock").glob("*.json"):
            validate_case(json.loads(path.read_text(encoding="utf-8")))

    def test_totals_are_derived_from_input(self):
        result = render_schema(self.case)
        self.assertEqual(
            result["income_total"],
            sum(row["amount"] for row in self.case["finance"]["income"]),
        )
        self.assertEqual(
            result["expense_total"],
            sum(row["amount"] for row in self.case["finance"]["expense"]),
        )

    def test_outputs_are_explicitly_drafts(self):
        standard = render_standard(self.case)
        donor = render_donor(self.case)
        self.assertIn("演示草稿", standard)
        self.assertIn("待确认", standard)
        self.assertIn("演示素材", donor)
        self.assertNotIn("所披露信息真实、完整", standard)

    def test_rejects_missing_or_invalid_finance(self):
        missing = deepcopy(self.case)
        del missing["operator"]
        with self.assertRaisesRegex(ValueError, "缺少必填字段"):
            validate_case(missing)

        negative = deepcopy(self.case)
        negative["finance"]["expense"][0]["amount"] = -1
        with self.assertRaisesRegex(ValueError, "非负数"):
            validate_case(negative)


if __name__ == "__main__":
    unittest.main()
