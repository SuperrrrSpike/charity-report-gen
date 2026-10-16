"""合规报告 JSON → 双版本 Markdown 渲染器。

输入：mock 目录里的一个 .json 案例文件
输出：
  - 标准合规版（机构 / 监管 视角）
  - 捐赠人友好版（C 端 / 公开 视角）
  - 监管表格 JSON Schema 版
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOCK = ROOT / "mock"
OUT = ROOT / "out"

REQUIRED_FIELDS = {
    "case_id",
    "title",
    "subtitle",
    "year",
    "category",
    "region",
    "operator",
    "summary",
    "timeline",
    "finance",
    "beneficiaries",
    "compliance",
}


def validate_case(case: dict) -> None:
    """Validate fields that are required by every renderer."""
    if not isinstance(case, dict):
        raise ValueError("案例必须是 JSON object")
    missing = sorted(REQUIRED_FIELDS - set(case))
    if missing:
        raise ValueError(f"缺少必填字段：{', '.join(missing)}")

    finance = case["finance"]
    if not isinstance(finance, dict):
        raise ValueError("finance 必须是 object")
    for group, label in (("income", "收入"), ("expense", "支出")):
        rows = finance.get(group)
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{label}明细不能为空")
        for index, row in enumerate(rows, start=1):
            amount = row.get("amount") if isinstance(row, dict) else None
            if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount < 0:
                raise ValueError(f"{label}第 {index} 行金额必须是非负数")
    if sum(row["amount"] for row in finance["expense"]) <= 0:
        raise ValueError("支出合计必须大于 0")

    if not isinstance(case["timeline"], list):
        raise ValueError("timeline 必须是数组")
    beneficiaries = case["beneficiaries"]
    if not isinstance(beneficiaries, dict) or not isinstance(beneficiaries.get("stories"), list):
        raise ValueError("beneficiaries.stories 必须是数组")
    compliance = case["compliance"]
    required_compliance = {
        "registration_no",
        "audit_firm",
        "audit_report_date",
        "public_disclosure_url",
    }
    if not isinstance(compliance, dict) or required_compliance - set(compliance):
        raise ValueError("compliance 字段不完整")


def fmt_money(amount: int, currency: str = "CNY") -> str:
    return f"{currency} {amount:,.0f}"


def render_standard(case: dict) -> str:
    """Render an internal-review draft with disclosure-related fields."""
    validate_case(case)
    f = case["finance"]
    income_total = sum(x["amount"] for x in f["income"])
    expense_total = sum(x["amount"] for x in f["expense"])
    surplus = income_total - expense_total

    md = []
    md.append(f"# {case['title']} — {case['year']} 年度合规报告")
    md.append("")
    md.append("> **演示草稿：发布前必须由机构、财务与法律责任人复核。**")
    md.append("")
    md.append(f"> 项目编号：{case['case_id']}")
    md.append(f"> 执行机构：{case['operator']}")
    md.append(f"> 登记证书号：{case['compliance']['registration_no']}")
    md.append(f"> 审计机构：{case['compliance']['audit_firm']}")
    md.append(f"> 审计报告日期：{case['compliance']['audit_report_date']}")
    md.append(f"> 信息披露链接：{case['compliance']['public_disclosure_url']}")
    md.append("")
    md.append("## 一、项目概况")
    md.append(f"- **主题**：{case['category']}｜{case['subtitle']}")
    md.append(f"- **覆盖区域**：{case['region']}")
    md.append(f"- **受益概览**：{case['beneficiaries']['headline']}")
    md.append("")
    md.append(case["summary"])
    md.append("")
    md.append("## 二、项目时间线")
    md.append("| 时间 | 关键事件 |")
    md.append("|---|---|")
    for tl in case["timeline"]:
        md.append(f"| {tl['date']} | {tl['event']} |")
    md.append("")
    md.append("## 三、收入明细")
    md.append(f"**收入合计：{fmt_money(income_total)}**")
    md.append("")
    md.append("| 收入来源 | 金额 |")
    md.append("|---|---:|")
    for x in f["income"]:
        md.append(f"| {x['source']} | {fmt_money(x['amount'])} |")
    md.append("")
    md.append("## 四、支出明细")
    md.append(f"**支出合计：{fmt_money(expense_total)}**")
    md.append(f"**结余：{fmt_money(surplus)}**")
    md.append("")
    md.append("| 支出项 | 金额 | 占比 |")
    md.append("|---|---:|---:|")
    for x in f["expense"]:
        pct = x["amount"] / expense_total * 100 if expense_total else 0
        md.append(f"| {x['item']} | {fmt_money(x['amount'])} | {pct:.1f}% |")
    md.append("")
    md.append("## 五、受益人故事")
    for s in case["beneficiaries"]["stories"]:
        md.append(f"- {s}")
    md.append("")
    md.append("## 六、发布前核验")
    md.append("- 核对登记信息、审计机构、审计日期和公开链接。")
    md.append("- 将全部财务数字与原始凭证或经确认的财务报表逐项勾稽。")
    md.append("- 由机构授权人员确认叙述、隐私处理和法定披露要求后签发。")
    md.append("")
    md.append(f"拟发布机构：{case['operator']}")
    md.append("签发状态：待确认")
    return "\n".join(md)


def render_donor(case: dict) -> str:
    """捐赠人友好版 Markdown — 重故事轻数字。"""
    validate_case(case)
    f = case["finance"]
    income_total = sum(x["amount"] for x in f["income"])
    expense_total = sum(x["amount"] for x in f["expense"])
    top = max(f["expense"], key=lambda x: x["amount"])

    md = []
    md.append(f"# {case['title']}")
    md.append("")
    md.append(f"**{case['subtitle']}**")
    md.append("")
    md.append(f"## 你的捐赠去了哪里？")
    md.append("")
    md.append(f"- 我们一共收到了 **{fmt_money(income_total)}** 善款")
    md.append(f"- 其中 **{int(top['amount'] / expense_total * 100)}%** 直接用于 **{top['item']}**")
    md.append(f"- 受益人覆盖：{case['beneficiaries']['headline']}")
    md.append("")
    md.append("## 受益人故事（演示素材）")
    md.append("")
    for s in case["beneficiaries"]["stories"]:
        md.append(f"> {s}")
        md.append("")
    md.append("## 时间线回顾")
    md.append("")
    for tl in case["timeline"]:
        md.append(f"- **{tl['date']}** — {tl['event']}")
    md.append("")
    md.append(f"查看披露材料（示例链接）：[打开]({case['compliance']['public_disclosure_url']})")
    return "\n".join(md)


def render_schema(case: dict) -> dict:
    """Render structured disclosure fields for downstream integration."""
    validate_case(case)
    f = case["finance"]
    return {
        "schema_version": "1.0",
        "case_id": case["case_id"],
        "title": case["title"],
        "year": case["year"],
        "operator": case["operator"],
        "registration_no": case["compliance"]["registration_no"],
        "audit_firm": case["compliance"]["audit_firm"],
        "income_total": sum(x["amount"] for x in f["income"]),
        "expense_total": sum(x["amount"] for x in f["expense"]),
        "income_breakdown": f["income"],
        "expense_breakdown": f["expense"],
        "beneficiaries": case["beneficiaries"]["headline"],
        "disclosure_url": case["compliance"]["public_disclosure_url"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", help="mock JSON 文件名（不带路径）")
    parser.add_argument("--out", default=None, help="输出目录")
    args = parser.parse_args()

    src = MOCK / args.case
    if not src.exists():
        sys.exit(f"找不到案例文件：{src}")
    case = json.loads(src.read_text(encoding="utf-8"))
    try:
        validate_case(case)
    except ValueError as error:
        sys.exit(f"案例数据无效：{error}")
    target = Path(args.out) if args.out else OUT / case["case_id"]
    target.mkdir(parents=True, exist_ok=True)

    (target / "standard.md").write_text(render_standard(case), encoding="utf-8")
    (target / "donor.md").write_text(render_donor(case), encoding="utf-8")
    (target / "schema.json").write_text(json.dumps(render_schema(case), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"渲染完成 → {target}")
    print(f"  standard.md  : {len((target / 'standard.md').read_text())} chars")
    print(f"  donor.md     : {len((target / 'donor.md').read_text())} chars")
    print(f"  schema.json  : {(target / 'schema.json').stat().st_size} bytes")


if __name__ == "__main__":
    main()
