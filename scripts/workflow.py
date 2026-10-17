"""可审计的公益报告提取、复核与渲染工作流。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable
from uuid import uuid4

from extract import MOCK, call_anthropic, call_openai
from render_report import render_donor, render_schema, render_standard, validate_case


class WorkflowError(ValueError):
    """Raised when a workflow command violates its state contract."""


_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|tk)[-_][A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{16,}"),
)


def _redact(value):
    if isinstance(value, str):
        result = value
        for pattern in _SECRET_PATTERNS:
            result = pattern.sub("[REDACTED]", result)
        return result
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex[:8]}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _append_audit(
    workspace: Path,
    event: str,
    from_state: str | None,
    to_state: str,
    metadata: dict | None = None,
) -> None:
    record = {
        "at_utc": _utc_now(),
        "event": event,
        "from_state": from_state,
        "to_state": to_state,
        "metadata": _redact(metadata or {}),
    }
    with (workspace / "audit.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _canonical_number(value: object) -> str:
    text = str(value).replace(",", "").strip()
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize(), "f")


def _source_numbers(material: str) -> set[str]:
    tokens = re.findall(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?", material)
    return {_canonical_number(token) for token in tokens}


def _required_numbers(case: dict) -> list[dict]:
    required = [{"field": "year", "value": case["year"]}]
    for index, row in enumerate(case["finance"]["income"]):
        required.append(
            {"field": f"finance.income[{index}].amount", "value": row["amount"]}
        )
    for index, row in enumerate(case["finance"]["expense"]):
        required.append(
            {"field": f"finance.expense[{index}].amount", "value": row["amount"]}
        )
    for index, token in enumerate(
        re.findall(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?", case["beneficiaries"]["headline"])
    ):
        required.append(
            {"field": f"beneficiaries.headline.number[{index}]", "value": token}
        )
    return required


def check_numeric_evidence(material: str, case: dict) -> dict:
    """Check that critical structured numbers also appear in source material."""
    source_numbers = _source_numbers(material)
    checked = []
    unsupported = []
    for item in _required_numbers(case):
        normalized = _canonical_number(item["value"])
        result = {
            "field": item["field"],
            "value": normalized,
            "supported": normalized in source_numbers,
        }
        checked.append(result)
        if not result["supported"]:
            unsupported.append({"field": result["field"], "value": normalized})
    return {
        "status": "passed" if not unsupported else "failed",
        "checked_count": len(checked),
        "supported_count": len(checked) - len(unsupported),
        "unsupported_numbers": unsupported,
        "checks": checked,
        "limitation": (
            "A matching token only proves that a number appeared in the supplied text; "
            "it does not verify the underlying document or transaction."
        ),
    }


def _extract_case(material: str, provider: str) -> dict:
    providers: dict[str, Callable[[str], dict]] = {
        "anthropic": call_anthropic,
        "openai": call_openai,
        "mock": lambda _: json.loads(
            (MOCK / "pediatric-aid.json").read_text(encoding="utf-8")
        ),
    }
    if provider not in providers:
        raise WorkflowError(f"Unsupported provider: {provider}")
    return providers[provider](material)


def _load_workflow(workspace: Path) -> dict:
    path = workspace / "workflow.json"
    if not path.exists():
        raise WorkflowError(f"Workflow does not exist: {workspace}")
    return json.loads(path.read_text(encoding="utf-8"))


def start_workflow(material: str, workspace: Path, *, provider: str) -> dict:
    workspace = Path(workspace)
    if workspace.exists():
        raise WorkflowError(f"Workflow workspace already exists: {workspace}")
    case = _extract_case(material, provider)
    workspace.mkdir(parents=True)
    source_bytes = material.encode("utf-8")
    source_sha256 = _sha256_bytes(source_bytes)
    (workspace / "source.md").write_bytes(source_bytes)
    workflow = {
        "schema_version": 1,
        "state": "ingested",
        "provider": provider,
        "source_sha256": source_sha256,
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "validation": None,
        "review": None,
        "artifacts": [],
    }
    _write_json(workspace / "workflow.json", workflow)
    _append_audit(
        workspace,
        "source_ingested",
        None,
        "ingested",
        {"provider": provider, "source_sha256": source_sha256},
    )

    _write_json(workspace / "extracted.json", case)
    _append_audit(workspace, "case_extracted", "ingested", "extracted")
    workflow["state"] = "extracted"
    try:
        validate_case(case)
        evidence = check_numeric_evidence(material, case)
        validation = {"structure": "passed", "numeric_evidence": evidence}
        next_state = "review_required" if evidence["status"] == "passed" else "validation_failed"
    except (KeyError, TypeError, ValueError) as exc:
        validation = {
            "structure": "failed",
            "error": str(exc),
            "numeric_evidence": None,
        }
        next_state = "validation_failed"
    workflow["state"] = next_state
    workflow["validation"] = validation
    workflow["updated_at_utc"] = _utc_now()
    _write_json(workspace / "workflow.json", workflow)
    _append_audit(
        workspace,
        "automatic_validation_completed",
        "extracted",
        next_state,
        {
            "structure": validation["structure"],
            "numeric_evidence": (
                validation["numeric_evidence"]["status"]
                if validation["numeric_evidence"]
                else "not_run"
            ),
        },
    )
    return workflow


def _render_approved_case(workspace: Path, case: dict) -> list[dict]:
    target = workspace / "out"
    outputs = {
        "standard.md": render_standard(case),
        "donor.md": render_donor(case),
        "schema.json": json.dumps(
            render_schema(case), ensure_ascii=False, indent=2
        ),
    }
    if target.exists():
        existing_names = (
            {path.name for path in target.iterdir()} if target.is_dir() else set()
        )
        matches = existing_names == set(outputs) and all(
            (target / name).is_file()
            and (target / name).read_text(encoding="utf-8") == content
            for name, content in outputs.items()
        )
        if not matches:
            raise WorkflowError(
                f"Existing output does not match approved case: {target}"
            )
        return [
            {
                "path": f"out/{name}",
                "sha256": _sha256_bytes((target / name).read_bytes()),
                "size_bytes": (target / name).stat().st_size,
            }
            for name in sorted(outputs)
        ]
    staging = workspace / f".out.{uuid4().hex[:8]}.tmp"
    staging.mkdir()
    try:
        for name, content in outputs.items():
            (staging / name).write_text(content, encoding="utf-8")
        artifacts = [
            {
                "path": f"out/{name}",
                "sha256": _sha256_bytes((staging / name).read_bytes()),
                "size_bytes": (staging / name).stat().st_size,
            }
            for name in sorted(outputs)
        ]
        staging.replace(target)
        return artifacts
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def review_workflow(
    workspace: Path,
    *,
    approve: bool,
    reviewer: str,
    note: str = "",
) -> dict:
    workspace = Path(workspace)
    workflow = _load_workflow(workspace)
    if approve and workflow["state"] == "rendered":
        return workflow
    if approve and workflow["state"] == "approved":
        case = json.loads((workspace / "extracted.json").read_text(encoding="utf-8"))
        artifacts = _render_approved_case(workspace, case)
        workflow["state"] = "rendered"
        workflow["artifacts"] = artifacts
        workflow["updated_at_utc"] = _utc_now()
        _write_json(workspace / "workflow.json", workflow)
        _append_audit(
            workspace,
            "reports_rendered",
            "approved",
            "rendered",
            {"artifacts": [item["path"] for item in artifacts]},
        )
        return workflow
    if workflow["state"] != "review_required":
        raise WorkflowError(
            f"Workflow must be in review_required state, got {workflow['state']}"
        )
    if not reviewer.strip():
        raise WorkflowError("Reviewer must be non-empty")

    decision = "approved" if approve else "rejected"
    safe_reviewer = _redact(reviewer.strip())
    safe_note = _redact(note.strip())
    workflow["state"] = decision
    workflow["review"] = {
        "decision": decision,
        "reviewer": safe_reviewer,
        "note": safe_note,
        "reviewed_at_utc": _utc_now(),
    }
    workflow["updated_at_utc"] = _utc_now()
    _write_json(workspace / "workflow.json", workflow)
    _append_audit(
        workspace,
        "human_review_completed",
        "review_required",
        decision,
        {"decision": decision, "reviewer": safe_reviewer, "note": safe_note},
    )
    if not approve:
        return workflow

    case = json.loads((workspace / "extracted.json").read_text(encoding="utf-8"))
    artifacts = _render_approved_case(workspace, case)
    workflow["state"] = "rendered"
    workflow["artifacts"] = artifacts
    workflow["updated_at_utc"] = _utc_now()
    _write_json(workspace / "workflow.json", workflow)
    _append_audit(
        workspace,
        "reports_rendered",
        "approved",
        "rendered",
        {"artifacts": [item["path"] for item in artifacts]},
    )
    return workflow


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="公益报告人工复核工作流")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="提取、校验并进入待审核状态")
    start.add_argument("--input", required=True, help="原始素材 Markdown 路径")
    start.add_argument("--workspace", required=True, help="新工作区目录")
    start.add_argument(
        "--provider", choices=("mock", "openai", "anthropic"), default="mock"
    )

    review = subparsers.add_parser("review", help="批准或拒绝待审核工作流")
    review.add_argument("--workspace", required=True)
    decision = review.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--note", "--reason", dest="note", default="")

    status = subparsers.add_parser("status", help="输出当前工作流摘要")
    status.add_argument("--workspace", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        workspace = Path(args.workspace)
        if args.command == "start":
            material = Path(args.input).read_text(encoding="utf-8")
            workflow = start_workflow(material, workspace, provider=args.provider)
        elif args.command == "review":
            workflow = review_workflow(
                workspace,
                approve=args.approve,
                reviewer=args.reviewer,
                note=args.note,
            )
        else:
            workflow = _load_workflow(workspace)
    except (OSError, json.JSONDecodeError, WorkflowError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    summary = {
        "state": workflow["state"],
        "provider": workflow["provider"],
        "source_sha256": workflow["source_sha256"],
        "artifact_count": len(workflow.get("artifacts", [])),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
