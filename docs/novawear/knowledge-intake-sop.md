# NOVAWEAR 知识库内容录入 SOP

## 目标

让员工用最低成本提交碎片知识，由 AI 辅助整理为结构一致的 Markdown 草稿，再由管理员审核发布。只有发布后的 approved 内容进入正式项目 Files 和后续向量索引。

## 员工提交

1. 进入项目空间 `NovaWear KB 优化版`。
2. 点击 `录入内容`。
3. 选择入口类型：
   - 文本：SOP、FAQ、培训话术、会议纪要。
   - 数据：SKU 表、尺码表、价格表、运营数据。
   - PDF：品牌手册、供应商资料、活动方案。
   - 其他：图片、链接、外部素材、暂未结构化资料。
4. 填写标题、业务分类、正文或文件说明。
5. 可选填写标签、来源说明、负责人和相关人。
6. 点击 `AI 整理` 生成草稿建议，或直接点击 `提交到待整理`。

员工提交后的内容只进入待整理区。MVP 当前待整理区是浏览器 localStorage 演示队列，不是跨设备团队后台；正式生产前必须迁移为后端持久化队列。

## AI 整理

`AI 整理` 只做辅助，不自动提交、不自动发布。MVP 当前使用后端 deterministic stub 返回结构化建议，接口已经是真实后端路由：

`POST /api/brand-kb/intake/assist`

返回内容包括：

- 建议标题。
- 业务分类。
- 内容类型。
- 权威等级。
- 建议标签。
- 缺失字段。
- 敏感风险。
- 质量提示。
- Markdown 草稿。

员工可点击 `应用 AI 建议` 把草稿写回表单；提交前仍可继续编辑。

## 必须人工复核

以下 AI 建议不得直接发布：

- 出现手机号、邮箱、订单号、会员信息。
- 出现真实供应商名称、采购成本、合同条款。
- 出现 API key、token、password、secret。
- 出现未公开价格、折扣、库存承诺。
- 数据类缺少数据口径、时间范围、字段说明或 owner。
- PDF 或其他素材只有文件名，没有正文摘要和适用范围。
- AI 输出为 `raw` 或包含“需管理员确认”。

有敏感风险时不得发布为 `official`。管理员必须脱敏、降级为 `reference/raw`，或退回补充来源。

## 管理员审核

管理员在 `待整理内容` 中处理每条提交：

1. 检查标题是否可被员工搜索。
2. 检查正文是否是可直接检索的一条知识原子。
3. 补齐来源说明、负责人、复核日期。
4. 选择内容类型：policy、faq、guide、raw_note、data_record、asset_reference。
5. 选择权威等级：official、reference、raw、deprecated。
6. 确认没有测试、报告、plan、PR、codex、eval 资产。
7. 点击 `发布到知识库`。

发布失败时，待整理项必须保留为 pending。发布成功只代表文件上传成功，索引完成仍需通过项目 Files 状态或后续回归验证。

## 不得进入正式知识库

- 测试用例、评估题、报告文件、计划文件、PR 草稿。
- Codex 工作记录、临时调试输出、聊天脏数据。
- 无来源、无负责人、无适用范围的片段。
- 未脱敏的个人信息、订单信息、会员信息。
- 真实供应商、采购成本、合同条款。
- 未确认库存、折扣、权益、活动承诺。
- 仅有文件名或图片名、没有可引用正文的素材。

## 发布 Markdown 标准

发布文件第一行包含 Onyx 可解析 metadata：

```md
<!-- ONYX_METADATA={"schema_version":"novawear_kb_intake_v1","lifecycle_status":"approved"} -->
```

随后保留 YAML frontmatter，供人工审计和外部工具使用：

```yaml
---
schema_version: novawear_kb_intake_v1
kb_intake_type: text
business_domain: service
content_kind: faq
authority_level: reference
lifecycle_status: approved
owner: "负责人"
review_at: "2026-09-21"
source_note: "客服会议纪要"
custom_tags: ["客服", "售后"]
ai_assisted: true
---
```

正文必须包含：

- `## 来源与治理`
- `## 正文`
- 摘要、适用范围、标准口径、例外边界、需要人工确认的信息。

AI 草稿不得保留顶层 `# 标题` 到正文中，发布器会统一生成 H1。

## 向量检索质量

- 首段正文要有业务摘要，避免只有治理字段。
- 一条文件只表达一个主要知识主题。
- FAQ 直接写问答，不要只写背景。
- 数据类必须把字段口径、时间范围和 owner 写清楚。
- PDF 必须转成 Markdown 摘要、页码依据和可引用口径。
- 禁止把 raw/pending/draft 内容通过普通 `Add Files` 绕过审核上传。

## 常见失败与处理

- AI 接口失败：继续手动提交，管理员后续整理。
- AI 标出敏感风险：先脱敏或退回，不可发布为 official。
- 发布后 Agent 检索不到：检查文件是否完成索引，再检查路由 scope 与 required docs。
- 数据类答案不稳定：补数据口径、时间范围、字段说明和 owner。
- PDF 只出现文件名：补 Markdown 摘要后再发布。
- 员工看不到待整理：MVP localStorage 局限；生产阶段必须迁移到后端 pending intake 表。
