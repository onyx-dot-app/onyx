from enum import StrEnum

from pydantic import BaseModel
from pydantic import Field


class BenchmarkProfile(StrEnum):
    CHAT_LITE = "chat_lite"
    DEEP_RESEARCH = "deep_research"


class BenchmarkCategory(StrEnum):
    FRESH_FACT = "fresh_fact"
    POLICY_RESEARCH = "policy_research"
    PRODUCT_COMPARISON = "product_comparison"
    TECHNICAL_RESEARCH = "technical_research"
    MARKET_RESEARCH = "market_research"
    CONSUMER_DECISION = "consumer_decision"
    FACT_CHECK = "fact_check"
    COMPANY_RESEARCH = "company_research"


class GlomiSearchBenchmarkCase(BaseModel):
    id: str
    profile: BenchmarkProfile
    category: BenchmarkCategory
    prompt: str
    expected_tools: list[str] = Field(default_factory=list)
    expected_behaviors: list[str] = Field(default_factory=list)


BENCHMARK_CASES: list[GlomiSearchBenchmarkCase] = [
    GlomiSearchBenchmarkCase(
        id="chat_fresh_ai_news",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.FRESH_FACT,
        prompt="最近一个月国内 AI 编程工具有什么重要变化？请给我简洁结论和来源。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["主动搜索", "打开高价值来源", "结论先行", "保留引用"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_policy_quick_check",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.POLICY_RESEARCH,
        prompt="现在中国对生成式 AI 服务备案有什么基本要求？请不要凭记忆回答。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["优先官方或监管来源", "说明适用范围", "标注不确定性"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_product_price",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.PRODUCT_COMPARISON,
        prompt="Cursor 和 Windsurf 现在个人版价格大概有什么区别？",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["查询最新价格页", "对比维度清晰", "避免过期价格"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_technical_version",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.TECHNICAL_RESEARCH,
        prompt="Next.js 15 现在推荐的缓存写法跟 14 有什么变化？",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["优先官方文档", "区分版本", "避免泛泛解释"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_company_fact",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.COMPANY_RESEARCH,
        prompt="月之暗面最近有没有发布新的 Kimi 模型或产品？",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["搜索最新信息", "优先官方公告", "给出时间线"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_fact_check_claim",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.FACT_CHECK,
        prompt="有人说 Manus 已经完全开源了，这是真的吗？帮我核实。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["核实主张", "查官方与代码来源", "区分完全开源和部分开放"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_consumer_decision",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.CONSUMER_DECISION,
        prompt="如果我主要写中文长文，Kimi、豆包、通义千问现在怎么选？",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["搜索近期产品状态", "结合中文写作场景", "给出选择建议"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_market_snapshot",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.MARKET_RESEARCH,
        prompt="中国 AI 搜索产品现在有哪些主要玩家？给我一个快速版。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["拆分玩家与定位", "使用近期来源", "输出简洁表格"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_github_release",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.TECHNICAL_RESEARCH,
        prompt="Playwright 最近几个版本有什么值得注意的更新？",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["优先 release notes", "按版本总结", "避免旧知识"],
    ),
    GlomiSearchBenchmarkCase(
        id="chat_conflicting_sources",
        profile=BenchmarkProfile.CHAT_LITE,
        category=BenchmarkCategory.FACT_CHECK,
        prompt="网上说某 AI 产品月活已经超过 ChatGPT，这种说法怎么判断靠不靠谱？",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["寻找原始数据来源", "说明口径差异", "指出证据不足"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_ai_coding_startup",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.MARKET_RESEARCH,
        prompt="请深度研究 2026 年 AI 编程工具还有没有创业机会，重点看中国市场。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["拆信息缺口", "中英双语搜索", "来源矩阵", "中文报告"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_china_ai_policy",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.POLICY_RESEARCH,
        prompt="请研究中国生成式 AI 应用上线前需要关注的备案、内容安全和合规要求。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["优先官方来源", "区分法规与解读", "列出风险与建议"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_ai_search_competition",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.MARKET_RESEARCH,
        prompt="请研究国内 AI 搜索和超级 Agent 产品格局，分析 Glomi AI 的切入机会。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["竞品分层", "产品定位", "机会与风险", "引用准确"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_model_provider_compare",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.PRODUCT_COMPARISON,
        prompt="请对比 Qwen、DeepSeek、Kimi、豆包在中文 Agent 产品中的适用性。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["比较模型能力", "搜索官方文档", "说明成本与工具调用风险"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_technical_rag_cn",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.TECHNICAL_RESEARCH,
        prompt="请研究中文 RAG 系统在 embedding、rerank、chunking 上的最佳实践。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["技术来源优先", "官方和论文结合", "给出工程建议"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_creator_tools",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.MARKET_RESEARCH,
        prompt="请研究中文自媒体创作者最可能为什么样的 AI Agent 工具付费。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["用户场景拆分", "消费决策来源", "机会排序"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_wechat_ecosystem",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.COMPANY_RESEARCH,
        prompt="请研究微信生态里适合 AI Agent 分发和获客的路径。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["来源覆盖微信规则", "案例研究", "风险提示"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_sandbox_deployment_cn",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.TECHNICAL_RESEARCH,
        prompt="请研究在国内云上部署代码沙箱和网页生成环境的技术方案与风险。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["技术方案对比", "安全风险", "云服务限制", "引用来源"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_pricing_strategy",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.MARKET_RESEARCH,
        prompt="请研究中国 C 端 AI 工具的订阅、积分和按量付费模式，给 Glomi AI 定价建议。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["价格来源", "竞品对比", "用户心理", "建议分层"],
    ),
    GlomiSearchBenchmarkCase(
        id="deep_fact_check_benchmark",
        profile=BenchmarkProfile.DEEP_RESEARCH,
        category=BenchmarkCategory.FACT_CHECK,
        prompt="请核查“AI Agent 产品留存普遍很差”这个判断是否成立，并找证据支持或反驳。",
        expected_tools=["web_search", "open_url"],
        expected_behaviors=["寻找数据来源", "保留冲突", "说明证据缺口"],
    ),
]
