# 慈善合规报告生成器 · Charity Compliance Report Generator

[![CI](https://github.com/SuperrrrSpike/charity-report-gen/actions/workflows/ci.yml/badge.svg)](https://github.com/SuperrrrSpike/charity-report-gen/actions/workflows/ci.yml)

> 个人原型项目 / vibe coding demo，目标投递：**腾讯公益平台·产品实习生（公益数字化 & AI 应用方向）**。

> **角色限定**：本项目为个人学习 / 作品集演示，所有数据均为虚构示例，**不构成任何真实捐赠、审计或合规披露**。

---

## 一句话定位

帮助公益机构把已核验的项目材料快速整理为内部审阅稿、捐赠人友好稿和结构化披露字段。

可恢复的人工复核工作流会记录素材哈希、校验结果和审批轨迹；只有人工批准后的案例才会生成正式输出文件。Provider 提取失败不会遗留阻塞重试的半成品工作区，也不会在错误信息中回显模型原文。

## 解决的问题

- 公益机构每年要做合规报告，格式严、手工整理耗时长，中小机构常因不合规被驳回。
- 捐赠人捐完看不到钱去了哪里，公示页风格不一、阅读门槛高。
- 平台/民政接收的格式各异，缺乏标准化 JSON Schema。

## 功能演示

直接打开 `web/index.html`：

- 首页 3 个真实风格 mock 案例（教育公平 / 生命救助 / 应急响应）
- 点进任一案例，**同屏**看到 B 端审阅稿 + C 端捐赠人友好版 + 结构化披露 JSON 三份
- 一键复制 Markdown / 打开结构化 JSON

## 仓库结构

```
charity-report-gen/
├── web/
│   ├── index.html        # 首页（3 个 mock 案例卡片）
│   └── demo.html         # 案例详情（B/C/Schema 三视图切换）
├── mock/
│   ├── spark-library.json    # 星火图书馆 · 教育公平
│   ├── pediatric-aid.json    # 重疾患儿 · 生命救助
│   └── flood-response.json   # 暴雨应急 · 应急响应
├── scripts/
│   ├── render_report.py  # JSON → Markdown / Schema 渲染器（无依赖）
│   ├── extract.py        # 原始素材 → JSON 结构（AI 结构化提取）
│   └── workflow.py       # 导入、校验、人工复核与发布工作流
├── examples/             # 仅供演示的虚构原始素材
├── out/                  # render_report.py 输出（每个案例一份）
│   └── <case-id>/
│       ├── standard.md   # B 端标准合规版
│       ├── donor.md      # C 端捐赠人友好版
│       └── schema.json   # 结构化披露字段
├── netlify.toml          # 部署配置
└── docs/PRD.md           # PRD 原文（5–8 天交付计划）
```

## 快速演示

### Agent 人工复核工作流

```bash
# 导入并校验原始素材；此时不会生成报告
python3 scripts/workflow.py start \
  --input examples/pediatric-aid-source.md \
  --workspace runs/pediatric-aid \
  --provider mock

# 查看状态并人工复核
python3 scripts/workflow.py status --workspace runs/pediatric-aid
python3 scripts/workflow.py review \
  --workspace runs/pediatric-aid \
  --approve \
  --reviewer "Reviewer Name" \
  --note "已核对示例素材"
```

批准后，`runs/pediatric-aid/out/` 才会出现标准版、捐赠人版和结构化披露文件。若批准后的渲染或状态写入中断，重复执行同一批准命令可安全续跑；已有产物与批准数据不一致时会拒绝覆盖。拒绝时使用 `--reject --reason "拒绝原因"`，工作流会保留审计记录但不会发布报告。

### 直接渲染预置案例

```bash
# 1. 渲染 mock 案例
python3 scripts/render_report.py spark-library.json
python3 scripts/render_report.py pediatric-aid.json
python3 scripts/render_report.py flood-response.json

# 2. 启动本地静态服务器
python3 -m http.server 8000
# 浏览器打开 http://127.0.0.1:8000/web/index.html
```

## AI 边界（重要）

- **AI 不能做**：财务数字生成（必须来自机构原始数据）、合规签字（必须机构法人确认）、审计结论。
- **AI 适合做**：结构化抽取、文案润色、跨格式改写（标准版 ↔ 捐赠人版）、风险字段初筛。
- **工作流约束**：财务与受益数据必须能在原始素材中找到证据，未通过人工批准不得生成发布文件。
- **mock 数据原则**：财务数字、机构登记号、审计日期均为虚构示例，不指向任何真实机构或项目。
- **发布责任**：程序输出始终是待审阅草稿，不能自动声明材料真实、完成审计或满足全部法定义务。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖 mock 数据结构、收支汇总、非法金额拒绝和草稿免责声明。

## vibe coding 演示主线

| 阶段 | 工具 | 用时 |
|---|---|---|
| PRD 草拟 | Claude（结构化拆解 + 字段设计） | 0.5 天 |
| Mock 数据 | Claude（虚构但合理的数据 + 受益人故事） | 0.5 天 |
| 渲染脚本 | Claude（无依赖 Python，3 类输出） | 0.5 天 |
| 单页 Web | Claude + Tailwind CDN（与 fitness-coach 同栈） | 0.5 天 |
| 部署 | Netlify（已配 netlify.toml） | 0.5 天 |
| **总计** | | **2.5 天** |

## 与腾讯公益 JD 的对应

| JD 要求 | 本项目体现 |
|---|---|
| 行业研究 / 机构洞察 | 3 个真实风格 mock 案例覆盖教育 / 医疗 / 应急 |
| 产品策略支持 / 度量指标 | 受益人 headline、收支占比、地理覆盖等 KPI 设计 |
| B 端 + C 端多角色多端产品 | B 端标准合规版 + C 端捐赠人友好版双视图 |
| AI 效率创新 / vibe coding | Claude 完成 PRD → 原型 2.5 天交付 |
| 公益 AI 场景应用 | 自动生成合规报告 + 监管 JSON Schema |
| 出海 / 港澳 | 受益人故事中已含粤港澳 / 桂北 / 粤东等地 |

## 本地部署到 Netlify

```bash
# 1. 注册 netlify-cli（已装可跳过）
npm install -g netlify-cli

# 2. 登录
netlify login

# 3. 初始化 + 部署
netlify init
netlify deploy --prod
```

`netlify.toml` 已配置：
- `/` → `/index.html`
- `/demo` → `/demo.html`
- `/out/*` → `out/*`（案例报告）
- 安全响应头（nosniff / DENY / strict-origin）

## 依赖

- Python 3.10+（标准库 only，无第三方包）
- AI 提取时需要 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`（`--provider mock` 模式不需）

## 不做的事

- 不指向任何真实公益机构 / 项目 / 个人
- 不提供捐赠入口、不连接任何支付接口
- 不替代法人签字 / 第三方审计
- 不打包发布到公开市场
