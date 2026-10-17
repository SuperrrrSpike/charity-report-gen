"""AI 结构化提取脚本（vibe coding 演示用）。

把项目原始素材（自由文本 / Markdown）→ JSON 结构，喂给 render_report.py。

注意：所有财务数字、机构登记号、审计日期必须**来自原始素材**，
AI 仅负责结构化抽取和文案润色，不得生成数字。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOCK = ROOT / "mock"

SYSTEM_PROMPT = """你是公益项目数据抽取助手。输入是机构提供的项目原始素材（自由文本 / Markdown），
输出必须是 JSON，严格遵循下面的 schema。**禁止编造数字或日期**——字段缺失就写 null。"""

SCHEMA = {
    "case_id": "string, 例: pediatric-aid-2025",
    "title": "string",
    "subtitle": "string",
    "year": "int",
    "category": "string, 例: 教育公平 / 生命救助 / 应急响应",
    "region": "string",
    "operator": "string, 执行机构名",
    "summary": "string, 200-300 字项目概要",
    "timeline": [{"date": "YYYY-MM or YYYY-MM-DD", "event": "string"}],
    "finance": {
        "currency": "CNY",
        "income": [{"source": "string", "amount": "int"}],
        "expense": [{"item": "string", "amount": "int"}],
    },
    "beneficiaries": {
        "headline": "string, 一行关键数字",
        "stories": ["string"],
    },
    "compliance": {
        "registration_no": "string",
        "audit_firm": "string",
        "audit_report_date": "YYYY-MM-DD",
        "public_disclosure_url": "string",
    },
}


class ExtractionError(ValueError):
    """Raised when a provider cannot return a usable structured case."""


def call_anthropic(material: str) -> dict:
    import urllib.request

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ExtractionError(
            "需要 ANTHROPIC_API_KEY 环境变量，或改用 --mock 走离线示例"
        )

    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": f"{json.dumps(SCHEMA, ensure_ascii=False)}\n\n---\n\n素材：\n{material}"}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    try:
        text = data["content"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ExtractionError("Anthropic response shape is invalid") from exc
    if not isinstance(text, str):
        raise ExtractionError("Anthropic response shape is invalid")
    return _parse_json(text)


def call_openai(material: str) -> dict:
    import urllib.request

    api_key = os.environ.get("OPENAI_API_KEY")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    if not api_key:
        raise ExtractionError("需要 OPENAI_API_KEY 环境变量")

    body = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{json.dumps(SCHEMA, ensure_ascii=False)}\n\n---\n\n素材：\n{material}"},
        ],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ExtractionError("OpenAI response shape is invalid") from exc
    if not isinstance(text, str):
        raise ExtractionError("OpenAI response shape is invalid")
    return _parse_json(text)


def _parse_json(text: str) -> dict:
    """LLM 偶尔会把 JSON 包在 markdown fence 里。"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ExtractionError("无法在 LLM 输出中找到 JSON 对象")
    return json.loads(m.group(0))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="原始素材文本或 .md")
    parser.add_argument("--out", required=True, help="输出 .json 路径")
    parser.add_argument("--provider", choices=["anthropic", "openai", "mock"], default="anthropic")
    args = parser.parse_args()

    material = Path(args.input).read_text(encoding="utf-8") if Path(args.input).exists() else args.input

    try:
        if args.provider == "mock":
            # 用预置案例当输出，方便无 LLM 演示
            result = json.loads(
                (MOCK / "pediatric-aid.json").read_text(encoding="utf-8")
            )
        elif args.provider == "anthropic":
            result = call_anthropic(material)
        else:
            result = call_openai(material)
    except (ExtractionError, OSError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {args.out}（provider={args.provider}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
