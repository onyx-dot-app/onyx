"use client";

import { SourceIcon } from "@/components/SourceIcon";
import SwitchList, { SwitchListItem } from "@/lib/tools/components/SwitchList";
import { useToolsPopover } from "@/lib/tools/providers";

export interface SourcesViewProps {
  onBack: () => void;
}

/** The popover's sources sub-view: one switch per source this agent can reach. */
export default function SourcesView({ onBack }: SourcesViewProps) {
  const {
    configuredSources,
    isSourceEnabled,
    toggleSource,
    enableAllSources,
    disableAllSources,
  } = useToolsPopover();

  const items: SwitchListItem[] = configuredSources.map((source) => ({
    id: source.uniqueKey,
    label: source.displayName,
    leading: <SourceIcon sourceType={source.internalName} iconSize={16} />,
    isEnabled: isSourceEnabled(source.uniqueKey),
    onToggle: () => toggleSource(source.uniqueKey),
  }));

  return (
    <SwitchList
      items={items}
      searchPlaceholder="Search Filters"
      allDisabled={configuredSources.every(
        (source) => !isSourceEnabled(source.uniqueKey)
      )}
      onDisableAll={disableAllSources}
      onEnableAll={enableAllSources}
      disableAllLabel="Disable All Sources"
      enableAllLabel="Enable All Sources"
      onBack={onBack}
    />
  );
}
