"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import AgentCard from "@/sections/agents/AgentCard";
import { AgentViewer } from "@/lib/agents/components";
import { useUser } from "@/providers/UserProvider";
import { hasPermission } from "@/lib/permissions/utils";
import { Permission } from "@/lib/types";
import { checkUserOwnsAgent } from "@/lib/agents/utils";
import { useAgents } from "@/lib/agents/hooks";
import { MinimalAgent } from "@/lib/agents/types";
import { SettingsLayouts } from "@opal/layouts";
import { GridSearchInput, NoItems, NoResults } from "@/lib/common/components";
import { useSearchableGrid } from "@/lib/common/hooks";
import TextSeparator from "@/refresh-components/TextSeparator";
import { Button, Tabs, Text } from "@opal/components";
import { SvgOnyxOctagon, SvgPlus } from "@opal/icons";
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
        <Text as="p" font="heading-h3" color="text-05">
          {title}
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          {description ?? ""}
        </Text>
      </div>
      {/* Every card is the same height: 8.5rem (136px). */}
      <div className="w-full grid grid-cols-1 md:grid-cols-2 auto-rows-[8.5rem] gap-2">
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

export default function AgentsCatalogPage() {
  const t = useTranslations("agents");
  const { agents, isLoading, error } = useAgents();
  const { user, permissions } = useUser();
  const canCreateAgent = hasPermission(permissions, Permission.ADD_AGENTS);
  const [searchQuery, setSearchQuery] = useState("");
  // One viewer for the listing, so the id lives here rather than in whichever
  // card happened to be clicked.
  const [viewedAgentId, setViewedAgentId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<"all" | "your">("all");

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

  const search = useSearchableGrid({
    query: searchQuery,
    setQuery: setSearchQuery,
    itemSelector: "[data-agent-card]",
  });

  return (
    <SettingsLayouts.Root
      loading={isLoading}
      error={!!error}
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
        actions={[
          <Button
            key="primary"
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
          </Button>,
        ]}
      >
        <div className="flex flex-col gap-2">
          <div className="flex flex-row items-center gap-2">
            <div className="flex-2">
              <GridSearchInput
                search={search}
                item={t("navigation.empty.item")}
                value={searchQuery}
                onChange={setSearchQuery}
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
        {/* A typed search reads as "nothing matched" even when there are no
            agents at all: that is what the user just asked. */}
        {nonBuiltinAgents.length === 0 && searchQuery.trim() === "" ? (
          <NoItems
            item={t("navigation.empty.item")}
            description={t("navigation.empty.description")}
          />
        ) : agentCount === 0 ? (
          <NoResults item={t("navigation.empty.item")} />
        ) : (
          // `contents`: a box for the grid navigation that adds no layout.
          <div ref={search.gridRef} className="contents">
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
          </div>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
