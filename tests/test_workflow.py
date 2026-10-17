from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow import (  # noqa: E402
    WorkflowError,
    check_numeric_evidence,
    review_workflow,
    start_workflow,
)


class NumericEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = json.loads(
            (ROOT / "mock" / "pediatric-aid.json").read_text(encoding="utf-8")
        )

    def test_supported_numbers_are_traced_to_source(self):
        material = self._material_for_case(self.case)

        report = check_numeric_evidence(material, self.case)

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["unsupported_numbers"], [])
        self.assertGreater(report["checked_count"], 5)

    def test_unsupported_finance_number_fails(self):
        material = self._material_for_case(self.case).replace("6,800,000", "6,700,000")

        report = check_numeric_evidence(material, self.case)

        self.assertEqual(report["status"], "failed")
        unsupported_fields = {item["field"] for item in report["unsupported_numbers"]}
        self.assertIn("finance.income[0].amount", unsupported_fields)

    @staticmethod
    def _material_for_case(case: dict) -> str:
        lines = [
            f"项目年度：{case['year']}",
            f"受益概览：{case['beneficiaries']['headline']}",
        ]
        lines.extend(
            f"收入 {row['source']}：{row['amount']:,} 元"
            for row in case["finance"]["income"]
        )
        lines.extend(
            f"支出 {row['item']}：{row['amount']:,} 元"
            for row in case["finance"]["expense"]
        )
        return "\n".join(lines)


class ReviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = json.loads(
            (ROOT / "mock" / "pediatric-aid.json").read_text(encoding="utf-8")
        )
        cls.material = NumericEvidenceTests._material_for_case(cls.case)

    def test_mock_workflow_requires_review_then_renders(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "case"

            started = start_workflow(self.material, workspace, provider="mock")

            self.assertEqual(started["state"], "review_required")
            self.assertTrue((workspace / "source.md").exists())
            self.assertTrue((workspace / "extracted.json").exists())
            self.assertFalse((workspace / "out").exists())

            completed = review_workflow(
                workspace,
                approve=True,
                reviewer="Demo Reviewer",
                note="已与示例原文逐项核对",
            )

            self.assertEqual(completed["state"], "rendered")
            self.assertEqual(
                {path.name for path in (workspace / "out").iterdir()},
                {"standard.md", "donor.md", "schema.json"},
            )
            audit_before = (workspace / "audit.jsonl").read_text(encoding="utf-8")
            repeated = review_workflow(
                workspace,
                approve=True,
                reviewer="Demo Reviewer",
            )
            self.assertEqual(repeated["state"], "rendered")
            self.assertEqual(
                (workspace / "audit.jsonl").read_text(encoding="utf-8"),
                audit_before,
            )

    def test_rejected_workflow_does_not_render(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "case"
            start_workflow(self.material, workspace, provider="mock")

            result = review_workflow(
                workspace,
                approve=False,
                reviewer="Demo Reviewer",
                note="需要补充原始凭证",
            )

            self.assertEqual(result["state"], "rejected")
            self.assertFalse((workspace / "out").exists())

    def test_validation_failure_cannot_be_approved(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "case"

            result = start_workflow("项目年度：2025", workspace, provider="mock")

            self.assertEqual(result["state"], "validation_failed")
            with self.assertRaisesRegex(WorkflowError, "review_required"):
                review_workflow(
                    workspace,
                    approve=True,
                    reviewer="Demo Reviewer",
                )

    def test_existing_workspace_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "case"
            start_workflow(self.material, workspace, provider="mock")

            with self.assertRaisesRegex(WorkflowError, "already exists"):
                start_workflow(self.material, workspace, provider="mock")

    def test_audit_log_excludes_source_and_secret_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "case"
            material = self.material + "\n内部备注：sk-not-for-audit-log"

            start_workflow(material, workspace, provider="mock")
            review_workflow(
                workspace,
                approve=False,
                reviewer="Demo Reviewer",
                note="误粘贴 sk-test1234567890abcdefghijklmnop",
            )
            audit = (workspace / "audit.jsonl").read_text(encoding="utf-8")
            workflow = (workspace / "workflow.json").read_text(encoding="utf-8")

            self.assertNotIn("sk-not-for-audit-log", audit)
            self.assertNotIn("sk-test1234567890abcdefghijklmnop", audit)
            self.assertNotIn("sk-test1234567890abcdefghijklmnop", workflow)
            self.assertIn("[REDACTED]", audit)
            self.assertNotIn(material, audit)
            for line in audit.splitlines():
                json.loads(line)

    def test_approved_workflow_can_retry_after_render_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "case"
            start_workflow(self.material, workspace, provider="mock")

            with mock.patch(
                "workflow._render_approved_case",
                side_effect=OSError("fixture render failure"),
            ):
                with self.assertRaisesRegex(OSError, "fixture render failure"):
                    review_workflow(
                        workspace,
                        approve=True,
                        reviewer="Demo Reviewer",
                    )

            interrupted = json.loads(
                (workspace / "workflow.json").read_text(encoding="utf-8")
            )
            self.assertEqual(interrupted["state"], "approved")

            completed = review_workflow(
                workspace,
                approve=True,
                reviewer="Ignored On Retry",
            )

            self.assertEqual(completed["state"], "rendered")
            events = [
                json.loads(line)["event"]
                for line in (workspace / "audit.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(events.count("human_review_completed"), 1)
            self.assertEqual(events.count("reports_rendered"), 1)

    def test_approved_workflow_recovers_after_output_publish_interruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "case"
            start_workflow(self.material, workspace, provider="mock")
            from workflow import _write_json as real_write_json

            def interrupt_final_state(path, payload):
                if payload.get("state") == "rendered":
                    raise OSError("fixture state write failure")
                real_write_json(path, payload)

            with mock.patch(
                "workflow._write_json", side_effect=interrupt_final_state
            ):
                with self.assertRaisesRegex(OSError, "fixture state write failure"):
                    review_workflow(
                        workspace,
                        approve=True,
                        reviewer="Demo Reviewer",
                    )

            self.assertTrue((workspace / "out/schema.json").exists())
            completed = review_workflow(
                workspace,
                approve=True,
                reviewer="Ignored On Retry",
            )
            self.assertEqual(completed["state"], "rendered")

    def test_retry_refuses_modified_published_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "case"
            start_workflow(self.material, workspace, provider="mock")
            from workflow import _write_json as real_write_json

            def interrupt_final_state(path, payload):
                if payload.get("state") == "rendered":
                    raise OSError("fixture state write failure")
                real_write_json(path, payload)

            with mock.patch(
                "workflow._write_json", side_effect=interrupt_final_state
            ):
                with self.assertRaises(OSError):
                    review_workflow(
                        workspace,
                        approve=True,
                        reviewer="Demo Reviewer",
                    )
            (workspace / "out/standard.md").write_text(
                "modified", encoding="utf-8"
            )

            with self.assertRaisesRegex(WorkflowError, "does not match"):
                review_workflow(
                    workspace,
                    approve=True,
                    reviewer="Ignored On Retry",
                )


if __name__ == "__main__":
    unittest.main()
