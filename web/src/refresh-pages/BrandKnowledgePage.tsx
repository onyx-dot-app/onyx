"use client";

import { useMemo } from "react";
import BrandKnowledgeAgentCard from "@/sections/cards/BrandKnowledgeAgentCard";
import { useAgents } from "@/lib/agents/hooks";
import type { MinimalAgent } from "@/lib/agents/types";
import { Button, Card, Tag } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import type { IconFunctionComponent } from "@opal/types";
import {
  SvgArrowRight,
  SvgBookOpen,
  SvgBubbleText,
  SvgCheckCircle,
  SvgFileText,
  SvgFiles,
  SvgFolderOpen,
  SvgHelpCircle,
  SvgLineChartUp,
  SvgPencilRuler,
  SvgShield,
  SvgUsers,
} from "@opal/icons";
import { MVP_READINESS } from "./brandKnowledgeMvpData";

interface BrandAgentRole {
  key: string;
  title: string;
  agentName: string;
  fallbackAgentId: number;
  description: string;
  capabilityTitle: string;
  capabilities: string[];
  demoQuestions: string[];
  icon: IconFunctionComponent;
}

const BRAND_AGENT_ROLES: BrandAgentRole[] = [
  {
    key: "design-planning",
    title: "设计企划",
    agentName: "NOVAWEAR 设计企划 Agent",
    fallbackAgentId: 1,
    description: "面向品牌定位、系列企划、产品故事和内容方向的知识库角色。",
    capabilityTitle: "适合让它处理",
    capabilities: [
      "提炼品牌定位、视觉关键词和系列主题",
      "梳理 SKU、面料、版型、价格带与卖点边界",
      "输出新品企划、campaign brief 和内容角度",
    ],
    demoQuestions: [
      "基于 FW2026 通勤胶囊，输出一版季度设计企划 brief。",
      "以 NW-OW-2601 为核心，写一段克制的产品故事。",
      "如果团队想把岚行描述成 Arc'teryx Veilance 平替，企划上应该如何改写？",
    ],
    icon: SvgPencilRuler,
  },
  {
    key: "product-training",
    title: "商品培训",
    agentName: "NOVAWEAR 商品培训 Agent",
    fallbackAgentId: 2,
    description: "面向门店导购、电商运营和培训材料的商品知识角色。",
    capabilityTitle: "适合让它处理",
    capabilities: [
      "把产品事实转换为导购话术和培训要点",
      "对比竞品、价格理由、搭配建议与异议处理",
      "生成直播脚本、PDP 文案和小红书内容提纲",
    ],
    demoQuestions: [
      "输出一份面向门店导购的 FW2026 商品培训大纲。",
      "顾客认为 1299 元通勤夹克太贵，导购怎么回应才不显得硬推？",
      "165cm、55kg、通勤为主的顾客试穿外套和轻机能裤，导购如何给尺码建议？",
    ],
    icon: SvgUsers,
  },
  {
    key: "customer-service",
    title: "客服售后",
    agentName: "NOVAWEAR 客服售后 Agent",
    fallbackAgentId: 3,
    description: "面向售后政策、质检判断、隐私边界和服务话术的知识库角色。",
    capabilityTitle: "适合让它处理",
    capabilities: [
      "回答退换货、物流、尺码和洗护相关问题",
      "按质量问题分级给出处理建议和升级路径",
      "识别不能承诺、不能查询、不能泄露的信息边界",
    ],
    demoQuestions: [
      "用户反馈轻机能裤穿两次大腿内侧起球，并要求立刻赔付，客服怎么处理？",
      "用户问 FW2026 活动赠品是否一定有货，并要求客服提前锁定，应该怎么回复？",
      "用户要求客服提供真实供应商名称、采购成本和合同条款，客服应该如何拒答？",
    ],
    icon: SvgHelpCircle,
  },
];

const KNOWLEDGE_STATS = [
  {
    label: "业务知识源",
    value: `${MVP_READINESS.import.businessSources} 篇 Markdown`,
    icon: SvgFiles,
  },
  {
    label: "评测资产",
    value: `${MVP_READINESS.import.evaluationSources} 篇已排除`,
    icon: SvgBookOpen,
  },
  {
    label: "RAG 验收",
    value: `${MVP_READINESS.rag.autoPass}/${MVP_READINESS.rag.total} 通过`,
    icon: SvgBubbleText,
  },
  {
    label: "Agent 回归",
    value: `${MVP_READINESS.agent.autoPass}/${MVP_READINESS.agent.total} 自动通过`,
    icon: SvgLineChartUp,
  },
];

const SOURCE_GROUPS = [
  {
    title: "品牌",
    docs: [
      "brand-positioning.md",
      "tone-of-voice.md",
      "visual-and-copy-dos-donts.md",
    ],
  },
  {
    title: "产品",
    docs: [
      "sku-master-fw2026.md",
      "outerwear-product-guide.md",
      "care-instructions.md",
    ],
  },
  {
    title: "客服",
    docs: [
      "return-and-exchange-policy.md",
      "quality-issue-handling.md",
      "faq.md",
    ],
  },
  {
    title: "供应链",
    docs: [
      "fabric-qc-standards.md",
      "defect-classification.md",
      "supplier-communication-rules.md",
    ],
  },
  {
    title: "竞品",
    docs: [
      "competitor-landscape.md",
      "arcteryx-veilance-comparison.md",
      "pricing-strategy.md",
    ],
  },
  {
    title: "活动",
    docs: [
      "fw2026-campaign-brief.md",
      "commuter-capsule-launch.md",
      "membership-campaign.md",
    ],
  },
];

const QUALITY_ITEMS = [
  {
    label: "Markdown 导入",
    value: `${MVP_READINESS.import.indexed}/${MVP_READINESS.import.uploaded}`,
    tone: "通过",
  },
  {
    label: "基础 RAG",
    value: `${MVP_READINESS.rag.autoPass}/${MVP_READINESS.rag.total}`,
    tone: "通过",
  },
  { label: "商品培训 Agent", value: "6/6", tone: "通过" },
  { label: "设计企划 Agent", value: "6/6", tone: "通过" },
  { label: "客服售后 Agent", value: "6/6", tone: "通过" },
  {
    label: "评测资产泄漏",
    value: `${MVP_READINESS.agent.projectEvaluationFileCount}`,
    tone: "通过",
  },
];

const IMPORT_WORKBENCH_ITEMS = [
  {
    title: "导入资产扫描",
    value: `${MVP_READINESS.import.businessSources} 业务 / ${MVP_READINESS.import.evaluationSources} 评测`,
    detail: "90-evaluation 默认排除，不进入用户检索源。",
  },
  {
    title: "批量上传索引",
    value: `${MVP_READINESS.import.uploaded}/${MVP_READINESS.import.indexed}`,
    detail: `${MVP_READINESS.import.failed} failed / ${MVP_READINESS.import.rejected} rejected / ${MVP_READINESS.import.zeroChunks} zero chunks`,
  },
  {
    title: "Chunk 统计",
    value: `${MVP_READINESS.import.chunkCount}`,
    detail: `项目 ${MVP_READINESS.project.name} / ${MVP_READINESS.project.id}`,
  },
  {
    title: "后验收",
    value: `${MVP_READINESS.rag.autoPass}/${MVP_READINESS.rag.total} RAG · ${MVP_READINESS.agent.autoPass}/${MVP_READINESS.agent.total} Agent`,
    detail: "三次 fresh rerun 已完成；当前无 P0/P1 人工复核项。",
  },
];

function resolveAgent(role: BrandAgentRole, agents: MinimalAgent[]) {
  return (
    agents.find((agent) => agent.name === role.agentName) ??
    agents.find((agent) => agent.id === role.fallbackAgentId) ??
    null
  );
}

function buildDemoHref(agentId: number | null | undefined, question: string) {
  const params = new URLSearchParams();
  if (agentId) {
    params.set("agentId", String(agentId));
  }
  params.set("user-prompt", question);
  params.set("send-on-load", "true");
  return `/app?${params.toString()}`;
}

function KnowledgeStat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: IconFunctionComponent;
}) {
  return (
    <Card padding="sm" rounding="sm" border="solid">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-08 bg-background-tint-02">
          <Icon size={18} />
        </div>
        <div className="min-w-0">
          <p className="text-xs text-text-03">{label}</p>
          <p className="truncate text-sm font-medium text-text-05">{value}</p>
        </div>
      </div>
    </Card>
  );
}

function SourceGroup({ title, docs }: { title: string; docs: string[] }) {
  return (
    <div className="rounded-08 border border-border-01 bg-background-100 p-3">
      <p className="text-sm font-medium text-text-05">{title}</p>
      <ul className="mt-2 flex flex-col gap-1">
        {docs.map((doc) => (
          <li
            key={doc}
            className="flex items-center gap-2 text-xs text-text-03"
          >
            <SvgFileText size={14} />
            <span className="truncate">{doc}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function BrandKnowledgePage() {
  const { agents, isLoading, error } = useAgents();
  const resolvedRoles = useMemo(
    () =>
      BRAND_AGENT_ROLES.map((role) => ({
        ...role,
        agent: resolveAgent(role, agents),
      })),
    [agents]
  );
  const readyRoleCount = resolvedRoles.filter((role) => role.agent).length;

  return (
    <SettingsLayouts.Root
      width="lg"
      data-testid="BrandKnowledgePage/container"
      aria-label="品牌知识库"
    >
      <SettingsLayouts.Header
        icon={SvgBookOpen}
        title="NOVAWEAR 企业知识库工作台"
        description="Sprint 1 Markdown-only 导入、索引、RAG 验收和岗位 Agent 回归的交付工作台。"
        rightChildren={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              href={`/app?projectId=${MVP_READINESS.project.id}`}
              icon={SvgFolderOpen}
            >
              打开知识库项目
            </Button>
            <Button href="/app/brand-knowledge/report" prominence="secondary">
              查看质量报告
            </Button>
          </div>
        }
      />

      <SettingsLayouts.Body>
        <div className="flex flex-col gap-6">
          <section className="rounded-08 border border-border-01 bg-background-tint-01 p-5">
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.5fr_1fr]">
              <div>
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <Tag title="Sprint 1 导入工作台" color="blue" />
                  <Tag title="虚拟服饰品牌" color="purple" />
                  <Tag title="标准 Vector RAG" color="green" />
                </div>
                <h1 className="text-2xl font-semibold leading-8 text-text-05">
                  从导入、索引到 RAG 与岗位 Agent 验收的一体化工作台。
                </h1>
                <p className="mt-3 text-sm leading-6 text-text-04">
                  NOVAWEAR 岚行已按 Sprint 1 口径导入
                  {MVP_READINESS.import.businessSources} 篇业务 Markdown，
                  并排除 {MVP_READINESS.import.evaluationSources} 篇
                  90-evaluation 评测资产。当前重点是把一次性 demo
                  推进成可复跑、可交付、可扩展的 MVP 基线。
                </p>
              </div>
              <Card padding="md" rounding="sm" border="solid">
                <div className="flex flex-col gap-3">
                  <div className="flex items-center gap-2">
                    <SvgShield size={18} />
                    <p className="font-medium text-text-05">
                      Sprint 1 验收状态
                    </p>
                  </div>
                  {QUALITY_ITEMS.map((item) => (
                    <div
                      key={item.label}
                      className="flex items-center justify-between gap-3 text-sm"
                    >
                      <span className="text-text-03">{item.label}</span>
                      <span className="font-medium text-text-05">
                        {item.value} · {item.tone}
                      </span>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          </section>

          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Tag title="默认品牌项目" color="blue" />
              <Tag
                title={`角色 Agent ${readyRoleCount}/3 已接入`}
                color="green"
              />
              <Tag title="标准 Vector RAG" color="purple" />
            </div>
            {error && (
              <p className="rounded-08 border border-status-error-03 bg-status-error-01 px-3 py-2 text-sm text-status-error-05">
                Agent 列表加载失败，请稍后刷新页面或检查后端服务。
              </p>
            )}
          </section>

          <section className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
            {KNOWLEDGE_STATS.map((stat) => (
              <KnowledgeStat key={stat.label} {...stat} />
            ))}
          </section>

          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-lg font-semibold text-text-05">
                导入工作台状态
              </h2>
              <p className="mt-1 text-sm text-text-03">
                以项目创建、Markdown-only 上传、等待索引和导入后验收为 Sprint 1
                P0 闭环。
              </p>
            </div>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
              {IMPORT_WORKBENCH_ITEMS.map((item) => (
                <Card
                  key={item.title}
                  padding="md"
                  rounding="sm"
                  border="solid"
                >
                  <p className="text-sm font-medium text-text-05">
                    {item.title}
                  </p>
                  <p className="mt-2 text-2xl font-semibold text-text-05">
                    {item.value}
                  </p>
                  <p className="mt-2 text-sm leading-5 text-text-03">
                    {item.detail}
                  </p>
                </Card>
              ))}
            </div>
          </section>

          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-lg font-semibold text-text-05">
                默认岗位角色
              </h2>
              <p className="mt-1 text-sm text-text-03">
                从岗位任务进入，比让用户先理解项目、文件和 Agent 配置更直接。
              </p>
            </div>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
              {resolvedRoles.map((role) => (
                <BrandKnowledgeAgentCard
                  key={role.key}
                  title={role.title}
                  description={role.description}
                  icon={role.icon}
                  capabilityTitle={role.capabilityTitle}
                  capabilities={role.capabilities}
                  demoQuestions={role.demoQuestions}
                  agent={role.agent}
                  isLoading={isLoading}
                  buildDemoHref={buildDemoHref}
                />
              ))}
            </div>
          </section>

          <section className="grid grid-cols-1 gap-4 lg:grid-cols-[1.25fr_0.75fr]">
            <div className="flex flex-col gap-3">
              <div>
                <h2 className="text-lg font-semibold text-text-05">
                  知识源示例
                </h2>
                <p className="mt-1 text-sm text-text-03">
                  回答会基于导入文档检索，不把模型流畅度当作事实来源。
                </p>
              </div>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                {SOURCE_GROUPS.map((group) => (
                  <SourceGroup key={group.title} {...group} />
                ))}
              </div>
            </div>

            <Card padding="md" rounding="sm" border="solid">
              <div className="flex h-full flex-col gap-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-08 bg-background-tint-02">
                    <SvgCheckCircle size={20} />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold text-text-05">
                      质量报告入口
                    </h2>
                    <p className="mt-1 text-sm leading-5 text-text-03">
                      汇总 RAG 基础验收、三角色 Agent
                      回归和人工复核建议，用于向企业用户解释可靠性边界。
                    </p>
                  </div>
                </div>
                <div className="flex flex-col gap-2 text-sm text-text-04">
                  <p>
                    最新基线：RAG {MVP_READINESS.rag.autoPass}/
                    {MVP_READINESS.rag.total}，Agent{" "}
                    {MVP_READINESS.agent.autoPass}/{MVP_READINESS.agent.total}{" "}
                    自动通过。
                  </p>
                  <p>fresh rerun：run 4/5/6 连续通过，交付基线已生成。</p>
                </div>
                <div className="mt-auto">
                  <Button
                    href="/app/brand-knowledge/report"
                    prominence="primary"
                    rightIcon={SvgArrowRight}
                  >
                    打开质量报告
                  </Button>
                </div>
              </div>
            </Card>
          </section>
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
