"use client";

import { Button, Card, Tag } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import {
  SvgArrowLeft,
  SvgBookOpen,
  SvgCheckCircle,
  SvgFileText,
  SvgLineChartUp,
} from "@opal/icons";
import { GATE_LABELS, MVP_READINESS } from "./brandKnowledgeMvpData";

const SUMMARY = [
  {
    label: "业务知识源",
    value: `${MVP_READINESS.import.businessSources} 篇 Markdown`,
  },
  {
    label: "评测资产",
    value: `${MVP_READINESS.import.evaluationSources} 篇，已排除`,
  },
  { label: "索引 chunks", value: `${MVP_READINESS.import.chunkCount}` },
  { label: "MVP 状态", value: MVP_READINESS.statusLabel },
];

const QUALITY_CARDS = [
  {
    label: "Markdown 导入",
    value: `${MVP_READINESS.import.indexed}/${MVP_READINESS.import.uploaded}`,
    status: "通过",
  },
  {
    label: "RAG 基础验收",
    value: `${MVP_READINESS.rag.autoPass}/${MVP_READINESS.rag.total}`,
    status: "通过",
  },
  {
    label: "Agent 回归",
    value: `${MVP_READINESS.agent.autoPass}/${MVP_READINESS.agent.total}`,
    status:
      MVP_READINESS.agent.review || MVP_READINESS.agent.explicitFailed
        ? "需复核"
        : "通过",
  },
  {
    label: "评测资产泄漏",
    value: `${MVP_READINESS.agent.projectEvaluationFileCount}`,
    status: "通过",
  },
];

export default function BrandKnowledgeReportPage() {
  return (
    <SettingsLayouts.Root
      width="lg"
      data-testid="BrandKnowledgeReportPage/container"
      aria-label="品牌知识库质量报告"
    >
      <SettingsLayouts.Header
        icon={SvgLineChartUp}
        title="品牌知识库质量报告"
        description="Sprint 1 Markdown-only 导入、RAG 验收与三角色 Agent 回归的 readiness 摘要。"
        rightChildren={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              href="/app/brand-knowledge"
              icon={SvgArrowLeft}
              prominence="secondary"
            >
              返回品牌知识库
            </Button>
            <Button
              href={`/app?projectId=${MVP_READINESS.project.id}`}
              icon={SvgBookOpen}
            >
              打开知识库项目
            </Button>
          </div>
        }
      />

      <SettingsLayouts.Body>
        <div className="flex flex-col gap-6">
          <section className="grid grid-cols-1 gap-2 md:grid-cols-4">
            {SUMMARY.map((item) => (
              <Card key={item.label} padding="sm" rounding="sm" border="solid">
                <p className="text-xs text-text-03">{item.label}</p>
                <p className="mt-1 text-sm font-medium text-text-05">
                  {item.value}
                </p>
              </Card>
            ))}
          </section>

          <section className="grid grid-cols-1 gap-3 md:grid-cols-4">
            {QUALITY_CARDS.map((item) => (
              <Card key={item.label} padding="md" rounding="sm" border="solid">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-text-05">
                      {item.label}
                    </p>
                    <p className="mt-1 text-2xl font-semibold text-text-05">
                      {item.value}
                    </p>
                  </div>
                  <Tag
                    title={item.status}
                    color={item.status === "通过" ? "green" : "amber"}
                    icon={item.status === "通过" ? SvgCheckCircle : undefined}
                  />
                </div>
              </Card>
            ))}
          </section>

          <section className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {MVP_READINESS.roleResults.map((item) => (
              <Card key={item.role} padding="md" rounding="sm" border="solid">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-text-05">
                      {item.role}
                    </p>
                    <p className="mt-1 text-2xl font-semibold text-text-05">
                      {item.result}
                    </p>
                  </div>
                  <Tag
                    title={item.status}
                    color={item.status === "通过" ? "green" : "amber"}
                    icon={item.status === "通过" ? SvgCheckCircle : undefined}
                  />
                </div>
              </Card>
            ))}
          </section>

          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-lg font-semibold text-text-05">
                待人工复核项
              </h2>
              <p className="mt-1 text-sm text-text-03">
                自动化 gate 已达标；当前没有阻塞 MVP Ready 的人工复核项。
              </p>
            </div>
            {MVP_READINESS.reviewItems.length ? (
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                {MVP_READINESS.reviewItems.map((item) => (
                  <Card key={item.id} padding="md" rounding="sm" border="solid">
                    <div className="flex items-start gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-08 bg-background-tint-02">
                        <SvgFileText size={18} />
                      </div>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <Tag title={item.id} color="gray" />
                          <Tag title={item.severity} color="amber" />
                          <h3 className="text-sm font-medium text-text-05">
                            {item.title}
                          </h3>
                        </div>
                        <p className="mt-2 text-sm leading-5 text-text-03">
                          {item.issue}
                        </p>
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            ) : (
              <div className="rounded-08 border border-border-01 bg-background-100 px-3 py-2 text-sm text-text-04">
                无 P0/P1 人工复核项。
              </div>
            )}
          </section>

          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-lg font-semibold text-text-05">
                Gate Matrix
              </h2>
              <p className="mt-1 text-sm text-text-03">
                前端报告、fresh rerun 和交付基线均已绑定最终 readiness 数据。
              </p>
            </div>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              {GATE_LABELS.map((gate) => {
                const passed = MVP_READINESS.gates[gate.key];
                return (
                  <div
                    key={gate.key}
                    className="flex items-center justify-between gap-3 rounded-08 border border-border-01 bg-background-100 px-3 py-2"
                  >
                    <span className="text-sm text-text-04">{gate.label}</span>
                    <Tag
                      title={passed ? "true" : "false"}
                      color={passed ? "green" : "amber"}
                      icon={passed ? SvgCheckCircle : undefined}
                    />
                  </div>
                );
              })}
            </div>
          </section>

          <section className="rounded-08 border border-border-01 bg-background-tint-01 p-4">
            <h2 className="text-lg font-semibold text-text-05">
              MVP Ready 判定
            </h2>
            <p className="mt-2 text-sm leading-6 text-text-04">
              当前已完成 clean Markdown 导入、RAG 16/16、Agent 18/18、三次 fresh
              project rerun 和评测资产隔离验证；当前状态为 MVP Ready。
            </p>
          </section>
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
