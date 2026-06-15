# 设计文档：普通 Chat 研究型回答策略

- **日期**：2026-06-15
- **产品**：Glomi AI
- **关联 Epic**：E3 超级对话调优
- **状态**：一期实施中

---

## Issues to Address

普通 chat 在调研、横评、选型类问题上已经能通过 `web_search` / `open_url` 获取较多证据，但最终回答缺少表达层约束。结果是普通对话经常输出几千甚至上万字，把候选项、来源、成本、风险、任务清单全部展开，用户反而很难抓住重点，也难以判断答案质量。

本问题不是搜索能力不足，而是普通 chat 缺少“研究后如何回答”的产品策略。

---

## Important Notes

- 不做固定输出模板。普通 chat 仍应让 Agent 自己决定用段落、列表、表格、短 memo、对比说明还是下一步计划。
- 不做固定档位。`web_search.mode=lite|medium|deep` 仍只表示检索强度，不表示最终回答长度。
- 不改 Deep Research。用户显式使用 Deep Research 时，长报告仍是合理预期。
- 不改 `llm_loop` / `dr_loop` runtime。第一期只通过 prompt policy 收敛普通 chat 的默认表达。

---

## Implementation Strategy

在共享搜索策略 `backend/onyx/prompts/search_strategy.py` 中新增普通 chat 研究型回答策略常量，并接入 `TOOL_DESCRIPTION_SEARCH_GUIDANCE`。

该策略约束的是回答原则，而不是固定结构：

- 普通 chat 的研究应让答案更容易判断，而不是默认变成完整报告。
- Agent 不使用固定模板，而是根据用户意图选择合适的回答形态。
- 默认先给最有用的判断，除非用户明确要求先探索可能性。
- 搜到很多资料时做综合归纳，不逐条搬运来源和中间发现。
- 让证据强弱、冲突和信息缺口可见，方便用户评估质量。
- deep search 不等于 long answer。
- 只有用户明确要求完整报告、详细展开、全面调研或文档式交付时，普通 chat 才输出长篇。

---

## Tests

新增和更新 prompt 单测：

- `backend/tests/unit/onyx/prompts/test_search_strategy.py`
  - 锁定普通 chat 研究型回答策略存在。
  - 锁定“不固定模板”“自适应回答形态”“deep search 不等于长答案”。
- `backend/tests/unit/onyx/prompts/test_tool_prompts.py`
  - 锁定该策略已接入普通 chat 搜索工具总指导。

验证命令：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\prompts
.venv\Scripts\python.exe -m ruff check backend\onyx\prompts backend\tests\unit\onyx\prompts
```
