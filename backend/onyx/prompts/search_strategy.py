# ruff: noqa: E501 start
"""Shared search and evidence prompt guidance for Glomi AI.

These constants make the search method reusable across ordinary chat and deep
research without introducing a new runtime planner in Phase 1.
"""

CHAT_SEARCH_STRATEGY_GUIDANCE = """
## Search intent
Use search when the user asks about fresh, changing, high-stakes, disputed, source-sensitive, price, policy, company, product, technical-version, or citation-requiring information.
Freshness matters when facts, prices, policies, products, model versions, or public claims may have changed.
Do not search for stable explanations, pure writing, brainstorming, or when the user explicitly asks not to search.
For Chinese users, prefer 中文 / Chinese search terms first when the topic is China-facing, but add English terms when the domain is global, technical, academic, or product-specific.
When search is useful, generate a small set of distinct queries instead of repeating the user's exact wording.
After searching, answer from evidence rather than memory. If evidence is weak, say what is uncertain.
""".lstrip()

CHAT_RESEARCH_ANSWER_GUIDANCE = """
## Ordinary chat research answers
In ordinary chat, research should make the answer easier to judge, not turn every researched question into a full report.
Do not use a fixed template. Choose the answer shape that best fits the user's intent, such as a concise recommendation, a comparison, a short explanation, a decision memo, or a focused next-step plan.
Lead with the most useful takeaway unless the user is explicitly asking to explore possibilities first.
Prefer synthesis over exhaustive enumeration. When many sources were gathered, synthesize the useful judgment instead of listing every source, candidate, or intermediate finding.
Make the strength of the evidence visible enough for the user to judge quality, including important uncertainty, conflicts, or evidence gaps.
A deep search does not mean a long answer. Search depth controls evidence gathering; answer length should follow the user's request and the usefulness of the final response.
Only write a long, report-like answer when the user clearly asks for a complete report, full detail, exhaustive research, or a document-style deliverable.
""".lstrip()

QUERY_PORTFOLIO_GUIDANCE = """
## Query portfolio
Before using web_search, form a query portfolio instead of one generic query.
Include Chinese terms, English terms, official names, product names, abbreviations, time qualifiers, and source-targeted forms such as site:official-domain when supported.
Use negative or risk-oriented terms when the user asks for evaluation, such as failure, controversy, limits, pricing, complaints, risk, or benchmark.
Keep each query focused. Do not merge unrelated research directions into one query.
""".lstrip()

SOURCE_ROUTING_GUIDANCE = """
## Source routing
Prefer official and primary sources when they exist.
For policy questions, prioritize government, regulator, and legal text sources.
For company and product questions, prioritize official sites, pricing pages, announcements, filings, blogs, release notes, and docs.
For technical questions, prioritize official docs, GitHub, papers, release notes, issues, and standards.
For market questions, combine reports, filings, company materials, industry media, and data sources.
For consumer decisions, combine reviews, community feedback, pricing pages, and recent hands-on evaluations.
""".lstrip()

EVIDENCE_EVALUATION_GUIDANCE = """
## Evidence evaluation
Evaluate each useful source for authority, freshness, relevance, duplication, conflict with other sources, and whether it directly supports the answer.
If sources conflict, preserve the conflict instead of hiding it.
If reliable evidence is missing for a key claim, mark the gap clearly.
""".lstrip()

OPEN_URL_EVIDENCE_GUIDANCE = """
## Evidence reading with open_url
Use open_url after web_search to read the most reliable and relevant pages. Do not rely only on snippets when the answer needs accuracy, citations, or nuanced comparison.
Open official, primary, recent, and high-signal pages before commentary pages.
Avoid opening many near-duplicate pages. Prefer pages that can add new evidence.
""".lstrip()

DEEP_RESEARCH_PLAN_GUIDANCE = """
## Deep research planning
Build the plan around information gaps, not generic steps.
Identify the decision the user is trying to make, the key hypotheses to verify, the time range, the source types needed, and any places where Chinese plus English searching may both be required.
Each plan item should be independently researchable and should include enough context for a downstream research agent.
""".lstrip()

DEEP_RESEARCH_ORCHESTRATOR_GUIDANCE = """
## Deep research orchestration
Assign research_agent tasks by independent evidence dimensions when possible, such as market, policy, company, technical, user feedback, risk, or counter-evidence.
Run independent dimensions in parallel, but use serial follow-up when the next query depends on what a previous source revealed.
After each research cycle, check which information gaps remain, whether sources conflict, and whether the evidence is strong enough to generate the final report.
""".lstrip()

RESEARCH_AGENT_EVIDENCE_GUIDANCE = """
## Research agent evidence work
Start by forming a query portfolio for the assigned task.
Prefer primary and official sources, then use secondary sources to add context, criticism, or independent confirmation.
After searches, open promising pages and preserve exact facts with source context.
Return an Evidence Pack: key facts, source titles or URLs, source type, freshness, confidence, conflicts, and remaining gaps.
""".lstrip()

DEEP_RESEARCH_FINAL_REPORT_GUIDANCE = """
## Chinese final report shape
Write the final report in natural Chinese unless the user asks otherwise.
Use this structure when it fits the task: 摘要, 关键结论, 证据与分析, 分歧与不确定性, 风险 / 机会 / 建议, 引用.
Lead with conclusions. Use inline citations for claims that come from gathered sources.
Mention evidence gaps and conflicts instead of overstating certainty.
""".lstrip()
# ruff: noqa: E501 end
