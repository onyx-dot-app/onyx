"use client";

import { useState, useMemo } from "react";
import { SvgEmpty, SvgFiles, SvgXOctagon } from "@opal/icons";
import { Content } from "@opal/layouts";
import Card from "@/refresh-components/cards/Card";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import Separator from "@/refresh-components/Separator";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { useConnectorStatus } from "@/lib/hooks";
import { useDocumentSets } from "@/lib/hooks/useDocumentSets";
import { useAgents } from "@/hooks/useAgents";
import { getSourceMetadata } from "@/lib/sources";
import type { ValidSources } from "@/lib/types";
import type { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import ResourceContent from "@/refresh-pages/admin/GroupsPage/SharedGroupResources/ResourceContent";
import ResourcePopover from "@/refresh-pages/admin/GroupsPage/SharedGroupResources/ResourcePopover";
import type { PopoverSection } from "@/refresh-pages/admin/GroupsPage/SharedGroupResources/ResourcePopover";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SharedGroupResourcesProps {
  selectedCcPairIds: number[];
  onCcPairIdsChange: (ids: number[]) => void;
  selectedDocSetIds: number[];
  onDocSetIdsChange: (ids: number[]) => void;
  selectedAgentIds: number[];
  onAgentIdsChange: (ids: number[]) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function SharedBadge() {
  return (
    <Text as="span" secondaryBody text03>
      Shared
    </Text>
  );
}

function SourceIconStack({ sources }: { sources: { source: ValidSources }[] }) {
  if (sources.length === 0) return null;

  const unique = Array.from(
    new Map(sources.map((s) => [s.source, s])).values()
  ).slice(0, 3);

  return (
    <div className="flex items-center shrink-0 px-0.5">
      {unique.map((s, i) => {
        const Icon = getSourceMetadata(s.source).icon;
        return (
          <div
            key={s.source}
            className="flex items-center justify-center size-4 rounded-04 bg-background-tint-00 border border-border-01 overflow-hidden"
            style={{ zIndex: unique.length - i, marginLeft: i > 0 ? -6 : 0 }}
          >
            <Icon />
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function SharedGroupResources({
  selectedCcPairIds,
  onCcPairIdsChange,
  selectedDocSetIds,
  onDocSetIdsChange,
  selectedAgentIds,
  onAgentIdsChange,
}: SharedGroupResourcesProps) {
  const [connectorSearch, setConnectorSearch] = useState("");
  const [agentSearch, setAgentSearch] = useState("");

  const { data: connectors = [] } = useConnectorStatus();
  const { documentSets } = useDocumentSets();
  const { agents } = useAgents();

  // --- Derived data ---

  const selectedCcPairSet = useMemo(
    () => new Set(selectedCcPairIds),
    [selectedCcPairIds]
  );
  const selectedDocSetSet = useMemo(
    () => new Set(selectedDocSetIds),
    [selectedDocSetIds]
  );
  const selectedAgentSet = useMemo(
    () => new Set(selectedAgentIds),
    [selectedAgentIds]
  );

  const selectedPairs = useMemo(
    () => connectors.filter((p) => selectedCcPairSet.has(p.cc_pair_id)),
    [connectors, selectedCcPairSet]
  );
  const selectedDocSets = useMemo(
    () => documentSets.filter((ds) => selectedDocSetSet.has(ds.id)),
    [documentSets, selectedDocSetSet]
  );
  const selectedAgentObjects = useMemo(
    () => agents.filter((a) => selectedAgentSet.has(a.id)),
    [agents, selectedAgentSet]
  );

  // --- Popover sections ---

  const connectorDocSetSections: PopoverSection[] = useMemo(() => {
    const q = connectorSearch.toLowerCase();

    const connectorItems = connectors
      .filter((p) => !q || (p.name ?? "").toLowerCase().includes(q))
      .map((p) => {
        const isSelected = selectedCcPairSet.has(p.cc_pair_id);
        return {
          key: `c-${p.cc_pair_id}`,
          disabled: isSelected,
          onSelect: () =>
            isSelected
              ? onCcPairIdsChange(
                  selectedCcPairIds.filter((id) => id !== p.cc_pair_id)
                )
              : onCcPairIdsChange([...selectedCcPairIds, p.cc_pair_id]),
          render: (dimmed: boolean) => (
            <LineItem
              interactive={!dimmed}
              muted={dimmed}
              icon={getSourceMetadata(p.connector.source).icon}
              rightChildren={
                p.groups.length > 0 || dimmed ? <SharedBadge /> : undefined
              }
            >
              {p.name ?? `Connector #${p.cc_pair_id}`}
            </LineItem>
          ),
        };
      });

    const docSetItems = documentSets
      .filter((ds) => !q || ds.name.toLowerCase().includes(q))
      .map((ds) => {
        const isSelected = selectedDocSetSet.has(ds.id);
        return {
          key: `d-${ds.id}`,
          disabled: isSelected,
          onSelect: () =>
            isSelected
              ? onDocSetIdsChange(
                  selectedDocSetIds.filter((id) => id !== ds.id)
                )
              : onDocSetIdsChange([...selectedDocSetIds, ds.id]),
          render: (dimmed: boolean) => (
            <LineItem
              interactive={!dimmed}
              muted={dimmed}
              icon={SvgFiles}
              rightChildren={
                ds.groups.length > 0 || dimmed ? <SharedBadge /> : undefined
              }
            >
              {ds.name}
            </LineItem>
          ),
        };
      });

    return [
      ...(connectorItems.length > 0
        ? [{ label: "Connectors", items: connectorItems }]
        : []),
      ...(docSetItems.length > 0
        ? [{ label: "Document Sets", items: docSetItems }]
        : []),
    ];
  }, [
    connectors,
    documentSets,
    connectorSearch,
    selectedCcPairSet,
    selectedDocSetSet,
    selectedCcPairIds,
    selectedDocSetIds,
    onCcPairIdsChange,
    onDocSetIdsChange,
  ]);

  const agentSections: PopoverSection[] = useMemo(() => {
    const q = agentSearch.toLowerCase();

    const items = agents
      .filter((a) => !q || a.name.toLowerCase().includes(q))
      .map((a) => {
        const isSelected = selectedAgentSet.has(a.id);
        return {
          key: `a-${a.id}`,
          disabled: isSelected,
          onSelect: () =>
            isSelected
              ? onAgentIdsChange(selectedAgentIds.filter((id) => id !== a.id))
              : onAgentIdsChange([...selectedAgentIds, a.id]),
          render: (dimmed: boolean) => (
            <AgentDropdownItem
              agent={a}
              shared={!a.is_public || dimmed}
              dimmed={dimmed}
            />
          ),
        };
      });

    return items.length > 0 ? [{ items }] : [];
  }, [
    agents,
    agentSearch,
    selectedAgentSet,
    selectedAgentIds,
    onAgentIdsChange,
  ]);

  // --- Handlers ---

  function removeConnector(id: number) {
    onCcPairIdsChange(selectedCcPairIds.filter((cid) => cid !== id));
  }

  function removeDocSet(id: number) {
    onDocSetIdsChange(selectedDocSetIds.filter((did) => did !== id));
  }

  function removeAgent(id: number) {
    onAgentIdsChange(selectedAgentIds.filter((aid) => aid !== id));
  }

  const hasSelectedResources =
    selectedPairs.length > 0 || selectedDocSets.length > 0;

  return (
    <SimpleCollapsible>
      <SimpleCollapsible.Header
        title="Shared with This Group"
        description="Share connectors, document sets, agents with members of this group."
      />
      <SimpleCollapsible.Content>
        <Card>
          <div className="flex flex-col gap-4 w-full">
            {/* Connectors & Document Sets */}
            <div className="flex flex-col gap-2">
              <div className="flex flex-col gap-1">
                <Text mainUiAction text04>
                  Connectors & Document Sets
                </Text>
                <ResourcePopover
                  placeholder="Add connectors, document sets"
                  searchValue={connectorSearch}
                  onSearchChange={setConnectorSearch}
                  sections={connectorDocSetSections}
                />
              </div>
              {hasSelectedResources ? (
                <div className="flex flex-wrap gap-1">
                  {selectedPairs.map((pair) => (
                    <ResourceContent
                      key={`c-${pair.cc_pair_id}`}
                      icon={getSourceMetadata(pair.connector.source).icon}
                      title={pair.name ?? `Connector #${pair.cc_pair_id}`}
                      description="Connector"
                      onRemove={() => removeConnector(pair.cc_pair_id)}
                    />
                  ))}
                  {selectedDocSets.map((ds) => (
                    <ResourceContent
                      key={`d-${ds.id}`}
                      icon={SvgFiles}
                      title={ds.name}
                      description={`Document Set - ${ds.cc_pair_summaries.length} Sources`}
                      infoContent={
                        <SourceIconStack sources={ds.cc_pair_summaries} />
                      }
                      onRemove={() => removeDocSet(ds.id)}
                    />
                  ))}
                </div>
              ) : (
                <Content
                  icon={SvgEmpty}
                  title="No connectors or document sets added"
                  description="Add connectors or document set to share with this group."
                  sizePreset="secondary"
                  variant="section"
                />
              )}
            </div>

            <Separator noPadding />

            {/* Agents */}
            <div className="flex flex-col gap-2">
              <div className="flex flex-col gap-1">
                <Text mainUiAction text04>
                  Agents
                </Text>
                <ResourcePopover
                  placeholder="Add agents"
                  searchValue={agentSearch}
                  onSearchChange={setAgentSearch}
                  sections={agentSections}
                />
              </div>
              {selectedAgentObjects.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {selectedAgentObjects.map((agent) => (
                    <ResourceContent
                      key={agent.id}
                      leftContent={
                        <div className="flex items-center justify-center shrink-0 size-5 p-0.5 rounded-04">
                          <AgentAvatar agent={agent} size={16} />
                        </div>
                      }
                      title={agent.name}
                      description="agent"
                      onRemove={() => removeAgent(agent.id)}
                    />
                  ))}
                </div>
              ) : (
                <Content
                  icon={SvgXOctagon}
                  title="No agents added"
                  description="Add agents to share with this group."
                  sizePreset="secondary"
                  variant="section"
                />
              )}
            </div>
          </div>
        </Card>
      </SimpleCollapsible.Content>
    </SimpleCollapsible>
  );
}

// ---------------------------------------------------------------------------
// AgentDropdownItem — agent row in the popover
// ---------------------------------------------------------------------------

function AgentDropdownItem({
  agent,
  shared,
  dimmed,
}: {
  agent: MinimalPersonaSnapshot;
  shared: boolean;
  dimmed: boolean;
}) {
  return (
    <LineItem
      interactive={!dimmed}
      muted={dimmed}
      icon={(_props) => <AgentAvatar agent={agent} size={16} />}
      description="agent"
      rightChildren={shared ? <SharedBadge /> : undefined}
    >
      {agent.name}
    </LineItem>
  );
}

export default SharedGroupResources;
