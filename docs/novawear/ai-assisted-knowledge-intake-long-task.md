# NOVAWEAR AI 辅助内容录入 Long Task Prompt

## 建议落文件路径

`/Users/blex/Projects/品牌知识库/upstream/onyx/docs/novawear/ai-assisted-knowledge-intake-long-task.md`

## 新窗口 Prompt

```md
你是 Codex，高级工程执行 Agent。请先把本 prompt 原样保存为：

/Users/blex/Projects/品牌知识库/upstream/onyx/docs/novawear/ai-assisted-knowledge-intake-long-task.md

然后开启自驱 long task，目标是把 NOVAWEAR 品牌知识库的“内容录入”链路推进为 MVP 阶段可验证、可演示、可继续扩展的最优 SOP：让员工最便捷地提交碎片化、不规范内容，通过大模型 API 辅助整理成标准知识库文件，再由管理员审核发布，最终为后端向量检索提供高质量、结构一致、可治理的知识源。

## 当前背景

仓库：

- Onyx 源码：/Users/blex/Projects/品牌知识库/upstream/onyx
- 当前页面：http://localhost:3000/app?projectId=1
- 容器：onyx-web_server-1、onyx-api_server-1、onyx-nginx-1

已完成：

- 项目空间 Files 区域已有“内容录入”入口。
- 支持文本 / 数据 / PDF / 其他四类入口。
- 当前 pending intake 是前端 localStorage MVP。
- 提交内容不进入正式 Files，不触发索引。
- 管理员可退回、发布。
- 发布时生成带 frontmatter 的 Markdown，并复用现有项目文件上传链路。

关键文件：

- web/src/sections/projects/ProjectContentIntakePanel.tsx
- web/src/sections/projects/ProjectContextPanel.tsx

## 北极星

构建“员工低摩擦录入 + AI 辅助标准化 + 管理员审核发布 + 向量检索高质量入库”的标准 SOP。

核心原则：

1. 员工录入必须简单、快速、低门槛。
2. AI 只做辅助整理、质检、补全建议，不自动发布。
3. 管理员负责最终审核、补口径、确认来源、发布入库。
4. 只有 approved 内容进入正式 Files 和后续向量索引。
5. 所有生成内容保留来源、负责人、时间、状态和风险提示。
6. 最终知识文件必须结构一致，便于 chunk、向量检索和引用。

## 多 Agent 对抗审查

如果可用，请开启至少 4 个子 Agent：

- Product/UX Agent：审查员工录入是否低摩擦。
- RAG/Knowledge Agent：审查 Markdown、metadata、chunk、检索质量。
- Backend/Security Agent：审查 API、secret、权限、审计、安全。
- QA/Eval Agent：审查测试、失败路径、验收口径。

如果没有 multi-agent 工具，则用法庭模式模拟四方对抗审查，并输出裁决。

## MVP 实现目标

新增“AI 整理”能力：

用户流程：

1. 用户打开“内容录入”。
2. 选择文本 / 数据 / PDF / 其他。
3. 粘贴碎片内容或补充文件说明。
4. 点击“AI 整理”。
5. 后端受控 API 调用模型，不允许前端暴露 API key。
6. 返回结构化建议。
7. 用户点击“应用 AI 建议”或继续手动编辑。
8. 提交进入 pending intake。
9. 管理员审核后发布为正式 Markdown。
10. 未审核内容不得进入正式 Files 或索引。

建议新增接口：

POST /api/brand-kb/intake/assist

输入：

{
  "project_id": 1,
  "intake_type": "text | data | pdf | other",
  "business_domain": "brand | product | marketing | sales | service | supply_chain | training | other",
  "title": "string",
  "raw_body": "string",
  "source_note": "string",
  "file_name": "string | null",
  "file_mime_type": "string | null"
}

输出：

{
  "suggested_title": "string",
  "business_domain": "string",
  "content_kind": "policy | faq | guide | raw_note | data_record | asset_reference",
  "authority_level": "official | reference | raw | deprecated",
  "suggested_tags": ["string"],
  "source_note": "string",
  "missing_fields": ["string"],
  "sensitive_risks": ["string"],
  "quality_warnings": ["string"],
  "markdown_draft": "string"
}

如果现有 Onyx 后端模型调用路径过重，允许先做后端 stub，但必须：
- 接口真实存在。
- 前端真实调用。
- 返回结构符合最终 contract。
- TODO 标注后续接入 provider 位置。
- 不伪装成生产级模型集成。

## 标准 Markdown 草稿

AI 输出必须偏向 RAG 友好：

---
kb_intake_type: text
business_domain: service
content_kind: faq
authority_level: reference
lifecycle_status: draft
owner: ""
review_at: ""
source_note: ""
custom_tags: []
ai_assisted: true
---

# 标题

## 摘要

## 适用场景

## 标准口径

## 操作步骤

## 禁止表达 / 风险边界

## 需要人工确认的信息

## 来源说明

发布后 lifecycle_status 必须变成 approved。

## 敏感信息规则

AI 辅助整理必须识别并提示：

- 手机号
- 邮箱
- 订单号
- 会员信息
- 真实供应商名称
- 采购成本
- 合同条款
- API key / token / password
- 内部未公开价格、折扣、库存承诺

默认行为：

- 不自动删除用户内容。
- 在 sensitive_risks 中提示。
- Markdown 草稿尽量脱敏或标注“需管理员确认”。
- 有敏感风险时不得默认 official。

## 前端要求

在 ProjectContentIntakePanel.tsx 中补充：

- AI 整理按钮
- loading 状态
- 失败提示
- 返回结果预览
- 应用 AI 建议
- 不自动覆盖用户手动编辑内容
- 模型失败时仍允许手动提交

按钮文案：

- AI 整理
- 应用 AI 建议
- 查看整理草稿
- 继续手动提交

## SOP 文档

新增或更新：

docs/novawear/knowledge-intake-sop.md

必须包含：

- 员工如何提交文本、数据、PDF、其他素材。
- 什么内容适合直接提交。
- 什么内容必须补来源。
- AI 整理如何使用。
- 哪些 AI 建议必须人工复核。
- 管理员如何审核、退回、发布。
- 什么内容不得进入正式知识库。
- 发布后 Markdown 格式标准。
- 向量检索质量注意事项。
- 常见失败案例和处理方式。

## 验收测试

至少运行：

- 前端 lint / 类型检查。
- 后端 Python 编译检查。
- 新 API 单元或最小集成测试。
- 前端交互验证。
- 容器健康检查。

交互场景：

1. 打开项目空间。
2. 打开内容录入。
3. 输入一条碎片文本。
4. 点击 AI 整理。
5. 返回建议展示。
6. 应用建议。
7. 提交到 pending。
8. 确认 pending 不进入正式 Files。
9. 管理员可看到待整理内容。
10. 模型接口失败时仍可手动提交。

验收标准：

- 员工 30 秒内可提交碎片文本。
- AI 能生成标准 Markdown 草稿。
- pending 不进入正式 Files。
- 未 approved 不进索引。
- 敏感风险有提示。
- 构建和静态检查通过。
- 容器 healthy。
- 不泄露 secret。
- 不回滚用户已有改动。

## Git/PR

创建分支：

codex/brand-kb-ai-assisted-intake

commit message：

Add AI-assisted brand KB intake workflow

如果有权限，推送并创建 draft PR。

PR 描述包含：

- 背景
- 技术方案
- AI 辅助录入流程
- 安全边界
- 测试结果
- 未解决风险
- 后续工作

## 工作方式

持续自驱执行，不要停在建议层面。

Loop：

1. inspect
2. plan
3. implement
4. verify
5. diagnose
6. fix
7. audit
8. repeat

最终输出：

- 改动摘要
- 文件列表
- 用户录入 SOP 结论
- AI 辅助链路说明
- 验收结果
- 未解决风险
- PR 链接或无法开 PR 原因
```
