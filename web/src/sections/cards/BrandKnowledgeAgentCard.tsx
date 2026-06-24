"use client";

import type { IconFunctionComponent } from "@opal/types";
import { Button, Card, Tag } from "@opal/components";
import {
  SvgArrowRight,
  SvgBubbleText,
  SvgCheckCircle,
  SvgSparkle,
} from "@opal/icons";
import type { MinimalAgent } from "@/lib/agents/types";

export interface BrandKnowledgeAgentCardProps {
  title: string;
  description: string;
  icon: IconFunctionComponent;
  capabilityTitle: string;
  capabilities: string[];
  demoQuestions: string[];
  agent: MinimalAgent | null;
  isLoading: boolean;
  buildDemoHref: (
    agentId: number | null | undefined,
    question: string
  ) => string;
}

export default function BrandKnowledgeAgentCard({
  title,
  description,
  icon: Icon,
  capabilityTitle,
  capabilities,
  demoQuestions,
  agent,
  isLoading,
  buildDemoHref,
}: BrandKnowledgeAgentCardProps) {
  const ready = !!agent;
  const href = ready ? `/app?agentId=${agent.id}` : "/app/agents";

  return (
    <Card padding="md" rounding="sm" border="solid">
      <div className="flex h-full flex-col gap-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-08 bg-background-tint-02">
              <Icon size={20} />
            </div>
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-text-05">{title}</h3>
              <p className="mt-1 text-sm leading-5 text-text-03">
                {description}
              </p>
            </div>
          </div>

          <Tag
            color={ready ? "green" : isLoading ? "gray" : "amber"}
            icon={ready ? SvgCheckCircle : undefined}
            title={ready ? "已接入" : isLoading ? "加载中" : "未找到"}
          />
        </div>

        <div className="flex flex-1 flex-col gap-2">
          <p className="text-xs font-medium text-text-03">{capabilityTitle}</p>
          <ul className="flex flex-col gap-1.5">
            {capabilities.map((capability) => (
              <li
                key={capability}
                className="flex items-start gap-2 text-sm leading-5 text-text-04"
              >
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-text-02" />
                <span>{capability}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="flex flex-col gap-2 rounded-08 bg-background-tint-01 p-3">
          <p className="text-xs font-medium text-text-03">推荐演示问题</p>
          <div className="flex flex-col gap-1.5">
            {demoQuestions.map((question) => (
              <div
                key={question}
                className="flex items-start justify-between gap-2 rounded-08 bg-background-100 px-2 py-2"
              >
                <p className="min-w-0 text-xs leading-5 text-text-04">
                  {question}
                </p>
                <Button
                  href={buildDemoHref(agent?.id, question)}
                  size="sm"
                  prominence="tertiary"
                  icon={SvgSparkle}
                  tooltip="发送演示问题"
                  disabled={isLoading}
                />
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border-01 pt-3">
          <p className="truncate text-xs text-text-03">
            {ready ? agent.name : "请先创建或恢复该默认 Agent"}
          </p>
          <Button
            href={href}
            size="md"
            prominence={ready ? "primary" : "secondary"}
            rightIcon={ready ? SvgBubbleText : SvgArrowRight}
            disabled={isLoading}
          >
            {ready ? "进入对话" : "查看智能体"}
          </Button>
        </div>
      </div>
    </Card>
  );
}
