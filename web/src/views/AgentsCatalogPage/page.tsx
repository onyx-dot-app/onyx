"use client";

import { useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { AgentCard, AgentViewer } from "@/lib/agents/components";
import { useUser } from "@/providers/UserProvider";
import { hasPermission } from "@/lib/permissions/utils";
import { Permission } from "@/lib/types";
import { checkUserOwnsAgent } from "@/lib/agents/utils";
import { useAgents } from "@/lib/agents/hooks";
import { MinimalAgent } from "@/lib/agents/types";
import { SettingsLayouts } from "@opal/layouts";
import { GridSearchInput, NoItems, NoResults } from "@/lib/common/components";
import { useSearchableGrid } from "@opal/hooks";
import { useNavigation } from "@opal/navigation";
import { Button, EndOfList, Tabs, Text } from "@opal/components";
import { SvgOnyxOctagon, SvgPlus } from "@opal/icons";
import { useAgentsFilters } from "@/sections/agents/AgentsFilters";

interface AgentsSectionProps {
  title: string;
  description?: string;
  agents: MinimalAgent[];
  /** The agent whose viewer is open, if any. */
  viewedAgentId: number | null;
  onView: (agentId: number) => void;
}

function AgentsSection({
  title,
  description,
  agents,
  viewedAgentId,
  onView,
}: AgentsSectionProps) {
  if (agents.length === 0) return null;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Text as="p" font="heading-section" color="text-05">
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
              viewing={agent.id === viewedAgentId}
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
  const navigation = useNavigation();
  const canCreateAgent = hasPermission(permissions, Permission.ADD_AGENTS);
  const [searchQuery, setSearchQuery] = useState("");
  // One viewer for the listing, so the id lives here rather than in whichever
  // card happened to be clicked.
  const [viewedAgentId, setViewedAgentId] = useState<number | null>(null);
  // The card that opened the viewer: focus goes back to it on close, so Tab
  // and the arrows carry on from where the user was.
  const viewerOpenerRef = useRef<HTMLElement | null>(null);
  function openViewer(agentId: number) {
    const opener = document.activeElement;
    viewerOpenerRef.current = opener instanceof HTMLElement ? opener : null;
    setViewedAgentId(agentId);
  }
  function closeViewer() {
    setViewedAgentId(null);
    const opener = viewerOpenerRef.current;
    viewerOpenerRef.current = null;
    // After the dialog unmounts and its own focus handling runs.
    requestAnimationFrame(() => opener?.focus());
  }
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
      // A failed refresh keeps the agents already shown.
      error={!!error && agents.length === 0}
      data-testid="AgentsPage/container"
      aria-label={t("navigation.page.ariaLabel")}
    >
      <AgentViewer agentId={viewedAgentId} onClose={closeViewer} />
      <SettingsLayouts.Header
        icon={SvgOnyxOctagon}
        title={t("navigation.header.title")}
        description={t("navigation.header.description")}
        actions={[
          <Button
            key="primary"
            {...(canCreateAgent ? navigation.linkTo("/app/agents/create") : {})}
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
            agents at all: that is what the user just asked. Without one, an
            empty list is either no agents at all, or the tab and filters
            leaving none. */}
        {agentCount === 0 && searchQuery.trim() !== "" ? (
          <NoResults item={t("navigation.empty.item")} />
        ) : agentCount === 0 ? (
          <NoItems
            item={t("navigation.empty.item")}
            description={
              nonBuiltinAgents.length === 0
                ? t("navigation.empty.description")
                : t("navigation.empty.filteredDescription")
            }
          />
        ) : (
          // `contents`: a box for the grid navigation that adds no layout.
          <div ref={search.gridRef} className="contents">
            <AgentsSection
              title={t("navigation.sections.featured.title")}
              description={t("navigation.sections.featured.description")}
              agents={featuredAgents}
              viewedAgentId={viewedAgentId}
              onView={openViewer}
            />
            <AgentsSection
              title={t("navigation.sections.all.title")}
              agents={allAgents}
              viewedAgentId={viewedAgentId}
              onView={openViewer}
            />
            <EndOfList
              paddingParallel={4}
              paddingPerpendicular={2}
              title={t("navigation.countSeparator.label", {
                count: agentCount,
              })}
            />
          </div>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
