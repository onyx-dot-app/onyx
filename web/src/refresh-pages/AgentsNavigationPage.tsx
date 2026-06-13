"use client";

import { useMemo, useState, useRef } from "react";
import AgentCard from "@/sections/agents/AgentCard";
import { useUser } from "@/providers/UserProvider";
import { checkUserOwnsAgent } from "@/lib/agents/utils";
import { useAgents } from "@/lib/agents/hooks";
import { MinimalAgent } from "@/lib/agents/types";
import Text from "@/refresh-components/texts/Text";
import { SettingsLayouts } from "@opal/layouts";
import TextSeparator from "@/refresh-components/TextSeparator";
import { Button, InputTypeIn, Tabs } from "@opal/components";
import { SvgPlus, SvgSparkle } from "@opal/icons";
import useOnMount from "@/hooks/useOnMount";
import { useAgentsFilters } from "@/sections/agents/AgentsFilters";

interface AgentsSectionProps {
  title: string;
  description?: string;
  agents: MinimalAgent[];
}

function AgentsSection({ title, description, agents }: AgentsSectionProps) {
  if (agents.length === 0) return null;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Text as="p" headingH3>
          {title}
        </Text>
        <Text as="p" secondaryBody text03>
          {description}
        </Text>
      </div>
      <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-2">
        {agents
          .sort((a, b) => b.id - a.id)
          .map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
      </div>
    </div>
  );
}

export default function AgentsNavigationPage() {
  const { agents } = useAgents();
  const { user } = useUser();
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"all" | "your">("all");
  const searchInputRef = useRef<HTMLInputElement>(null);

  useOnMount(() => {
    searchInputRef.current?.focus();
  });

  const nonBuiltinAgents = useMemo(
    () => agents.filter((a) => !a.builtin_persona),
    [agents]
  );

  const { filtered: agentsFilteredByFilters, filterBar } =
    useAgentsFilters(nonBuiltinAgents);

  const memoizedCurrentlyVisibleAgents = useMemo(() => {
    return agentsFilteredByFilters.filter((agent) => {
      const nameMatches = agent.name
        .toLowerCase()
        .includes(searchQuery.toLowerCase());
      const labelMatches = agent.labels?.some((label) =>
        label.name.toLowerCase().includes(searchQuery.toLowerCase())
      );

      const mineFilter =
        activeTab === "your" ? checkUserOwnsAgent(user, agent) : true;

      return (nameMatches || labelMatches) && mineFilter;
    });
  }, [agentsFilteredByFilters, searchQuery, activeTab, user]);

  const featuredAgents = memoizedCurrentlyVisibleAgents.filter(
    (agent) => agent.is_featured
  );
  const allAgents = memoizedCurrentlyVisibleAgents.filter(
    (agent) => !agent.is_featured
  );

  const agentCount = featuredAgents.length + allAgents.length;

  return (
    <SettingsLayouts.Root
      data-testid="AgentsPage/container"
      aria-label="智能体页面"
    >
      <SettingsLayouts.Header
        icon={SvgSparkle}
        title="智能体"
        description="为你和团队的使用场景定制 AI 行为与知识。"
        rightChildren={
          <Button
            href="/app/agents/create"
            icon={SvgPlus}
            aria-label="AgentsPage/new-agent-button"
          >
            新建智能体
          </Button>
        }
      >
        <div className="flex flex-col gap-2">
          <div className="flex flex-row items-center gap-2">
            <div className="flex-2">
              <InputTypeIn
                ref={searchInputRef}
                placeholder="搜索智能体..."
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                searchIcon
              />
            </div>
            <div className="flex-1">
              <Tabs
                value={activeTab}
                onValueChange={(value) => setActiveTab(value as "all" | "your")}
              >
                <Tabs.List>
                  <Tabs.Trigger value="all">全部智能体</Tabs.Trigger>
                  <Tabs.Trigger value="your">我的智能体</Tabs.Trigger>
                </Tabs.List>
              </Tabs>
            </div>
          </div>
          <div className="flex flex-row gap-2">{filterBar}</div>
        </div>
      </SettingsLayouts.Header>

      {/* Agents List */}
      <SettingsLayouts.Body>
        {agentCount === 0 ? (
          <Text
            as="p"
            className="w-full h-full flex flex-col items-center justify-center py-12"
            text03
          >
            未找到智能体
          </Text>
        ) : (
          <>
            <AgentsSection
              title="精选智能体"
              description="由你的团队精选"
              agents={featuredAgents}
            />
            <AgentsSection title="全部智能体" agents={allAgents} />
            <TextSeparator
              count={agentCount}
              text="个智能体"
            />
          </>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
