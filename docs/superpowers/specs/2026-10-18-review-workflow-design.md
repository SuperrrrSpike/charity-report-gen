# 公益报告人工复核工作流设计

## 目标

把现有“一次提取后直接写 JSON”的脚本改造成可恢复、可审计的 Agent 工作流：

```text
原始素材 → AI/Mock 提取 → 结构校验 → 数字证据核对 → 待人工复核 → 批准 → 报告渲染
```

任何模型输出都不能绕过结构校验和人工批准。工作流用于演示 AI Agent 编排与合规边界，不声称替代真实审计或法律审查。

## 状态

- `ingested`：原始素材已读取并记录 SHA-256。
- `extracted`：Provider 已返回结构化案例。
- `validation_failed`：结构或数字证据检查失败，禁止批准和渲染。
- `review_required`：自动检查通过，等待人工决定。
- `rejected`：人工拒绝，可记录理由，但不生成正式产物。
- `approved`：人工批准并记录审核人、时间和说明。
- `rendered`：标准稿、捐赠人稿和结构化 JSON 已生成。

状态只能按允许的方向流转。重复执行 `start` 不覆盖现有工作区；重复渲染已完成工作流时保持幂等。

## 数字证据

工作流从原始素材中提取规范化数字词元，并核对结构化案例中的年度、收入、支出和受益人标题中的数字。未能在原文找到的关键数字列入 `unsupported_numbers`，状态进入 `validation_failed`。

数字格式允许逗号、货币符号和常见百分号差异。该检查只能证明文本中出现过数字，不能证明凭证真实，因此批准前仍需要人工核对原始凭证。

## 审计记录

每个工作区包含：

- `source.md`：原始素材副本。
- `extracted.json`：Provider 原始结构化结果。
- `workflow.json`：当前状态、来源哈希、Provider、检查结果和人工审核信息。
- `audit.jsonl`：只追加的状态事件，不保存 API 密钥。
- `out/`：批准后生成的三类报告。

审计事件包含 UTC 时间、事件名、前后状态和最小必要元数据。不得写入环境变量、请求头或完整模型响应日志。

## 命令行

```bash
python scripts/workflow.py start --input examples/pediatric-aid-source.md --workspace runs/pediatric-aid --provider mock
python scripts/workflow.py review --workspace runs/pediatric-aid --approve --reviewer "Demo Reviewer"
python scripts/workflow.py status --workspace runs/pediatric-aid
```

拒绝使用 `--reject --reason`。批准后自动渲染，只有 `rendered` 状态代表完整成功。

## 测试

- 状态转移、重复启动、未审核渲染和拒绝路径。
- 原文支持与不支持的财务数字。
- 审计日志只追加且不包含密钥。
- Mock 端到端工作流生成三类产物。
- CI 执行单元测试和一次离线端到端演示。

## 非目标

不增加真实用户上传服务、数据库、支付、分享链接或自动法律结论。OpenAI/Anthropic 调用仍是可选 Provider，CI 与演示默认完全离线。
