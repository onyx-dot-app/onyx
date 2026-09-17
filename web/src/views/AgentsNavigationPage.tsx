"use client";

import { useMemo, useState, useRef } from "react";
import { useTranslations } from "next-intl";
import AgentCard from "@/sections/agents/AgentCard";
import { AgentViewer } from "@/lib/agents/components";
import { useUser } from "@/providers/UserProvider";
import { hasPermission } from "@/lib/permissions";
import { Permission } from "@/lib/types";
import { checkUserOwnsAgent } from "@/lib/agents/utils";
import { useAgents } from "@/lib/agents/hooks";
import { MinimalAgent } from "@/lib/agents/types";
import Text from "@/refresh-components/texts/Text";
import { SettingsLayouts } from "@opal/layouts";
import TextSeparator from "@/refresh-components/TextSeparator";
import { Button, InputTypeIn, Tabs } from "@opal/components";
import { SvgOnyxOctagon, SvgPlus } from "@opal/icons";
import useOnMount from "@/hooks/useOnMount";
import { useAgentsFilters } from "@/sections/agents/AgentsFilters";

interface AgentsSectionProps {
  title: string;
  description?: string;
  agents: MinimalAgent[];
  onView: (agentId: number) => void;
}

function AgentsSection({
  title,
  description,
  agents,
  onView,
}: AgentsSectionProps) {
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
            <AgentCard
              key={agent.id}
              agent={agent}
              onView={() => onView(agent.id)}
            />
          ))}
      </div>
    </div>
  );
}

// e2e locator, not user copy.
const NEW_AGENT_BUTTON_ARIA_LABEL = "AgentsPage/new-agent-button";

export default function AgentsNavigationPage() {
  const t = useTranslations("agents");
  const { agents } = useAgents();
  const { user, permissions } = useUser();
  const canCreateAgent = hasPermission(permissions, Permission.ADD_AGENTS);
  const [searchQuery, setSearchQuery] = useState("");
  // One viewer for the listing, so the id lives here rather than in whichever
  // card happened to be clicked.
  const [viewedAgentId, setViewedAgentId] = useState<number | null>(null);
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
      aria-label={t("navigation.page.ariaLabel")}
    >
      <AgentViewer
        agentId={viewedAgentId}
        onClose={() => setViewedAgentId(null)}
      />
      <SettingsLayouts.Header
        icon={SvgOnyxOctagon}
        title={t("navigation.header.title")}
        description={t("navigation.header.description")}
        rightChildren={
          <Button
            href={canCreateAgent ? "/app/agents/create" : undefined}
            icon={SvgPlus}
            aria-label={NEW_AGENT_BUTTON_ARIA_LABEL}
            disabled={!canCreateAgent}
            tooltip={
              !canCreateAgent
                ? t("navigation.newAgent.noPermission.tooltip")
                : undefined
            }
          >
            {t("navigation.newAgent.label")}
          </Button>
        }
      >
        <div className="flex flex-col gap-2">
          <div className="flex flex-row items-center gap-2">
            <div className="flex-2">
              <InputTypeIn
                ref={searchInputRef}
                placeholder={t("navigation.search.placeholder")}
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
                  <Tabs.Trigger value="all">
                    {t("navigation.tabs.all.label")}
                  </Tabs.Trigger>
                  <Tabs.Trigger value="your">
                    {t("navigation.tabs.your.label")}
                  </Tabs.Trigger>
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
            {t("navigation.empty.description")}
          </Text>
        ) : (
          <>
            <AgentsSection
              title={t("navigation.sections.featured.title")}
              description={t("navigation.sections.featured.description")}
              agents={featuredAgents}
              onView={setViewedAgentId}
            />
            <AgentsSection
              title={t("navigation.sections.all.title")}
              agents={allAgents}
              onView={setViewedAgentId}
            />
            <TextSeparator
              count={agentCount}
              text={t("navigation.countSeparator.label", {
                count: agentCount,
              })}
            />
          </>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
