// Web's source list has a filter box; this one is short enough to go without.
import { getSourceMeta, type DocumentSource } from "@/chat/sources";
import { ConnectorSourceIcon } from "@/components/chat/ConnectorSourceIcon";
import { LineItemButton } from "@/components/ui/line-item-button";
import { Switch } from "@/components/ui/switch";
import { useComposerTools } from "@/state/ComposerToolsProvider";
import SvgPlug from "@/icons/plug";
import SvgUnplug from "@/icons/unplug";

function sourceLabel(source: DocumentSource): string {
  return getSourceMeta(source)?.displayName ?? source;
}

export function SourceSwitchList() {
  const {
    sourceOptions,
    enabledSourceCount,
    isSourceEnabled,
    toggleSource,
    enableAllSources,
    disableAllSources,
  } = useComposerTools();

  const allDisabled = enabledSourceCount === 0;

  return (
    <>
      <LineItemButton
        icon={allDisabled ? SvgPlug : SvgUnplug}
        title={allDisabled ? "Enable All" : "Disable All"}
        titleMaxLines={1}
        sizePreset="main-ui"
        variant="section"
        onPress={allDisabled ? enableAllSources : disableAllSources}
      />

      {sourceOptions.map((source) => {
        const enabled = isSourceEnabled(source);
        const label = sourceLabel(source);
        return (
          <LineItemButton
            key={source}
            leading={<ConnectorSourceIcon source={source} />}
            title={label}
            titleMaxLines={1}
            sizePreset="main-ui"
            variant="section"
            // Web reacts to the switch alone; 32×18 is a small touch target, so the row does too.
            onPress={() => toggleSource(source)}
            rightChildren={
              <Switch
                checked={enabled}
                onCheckedChange={() => toggleSource(source)}
                accessibilityLabel={`Toggle ${label}`}
              />
            }
          />
        );
      })}
    </>
  );
}
