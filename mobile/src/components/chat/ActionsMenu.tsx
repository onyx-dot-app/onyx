/*
 * A bottom sheet, not web's trigger-anchored popover: the mobile composer is keyboard-sticky, so
 * an anchored panel would chase a moving anchor.
 */
import { useState } from "react";
import { Keyboard, ScrollView } from "react-native";

import { ActionLineItem } from "@/components/chat/ActionLineItem";
import { SourceSwitchList } from "@/components/chat/SourceSwitchList";
import { Button } from "@/components/ui/button";
import { LineItemButton } from "@/components/ui/line-item-button";
import { Sheet } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { useComposerTools } from "@/state/ComposerToolsProvider";
import SvgHourglass from "@/icons/hourglass";
import SvgSliders from "@/icons/sliders";

const MAX_LIST_HEIGHT = 420;

export function ActionsMenu() {
  const {
    showDeepResearch,
    deepResearchEnabled,
    toggleDeepResearch,
    actionTools,
    unavailableToolIds,
    forcedToolId,
    toggleForcedTool,
    disabledToolIds,
    toggleToolEnabled,
    sourceToolId,
    sourceOptions,
    enabledSourceCount,
  } = useComposerTools();
  const [open, setOpen] = useState(false);
  const [showSources, setShowSources] = useState(false);

  // Deep research lives in this sheet, so an agent with no action tools still needs the trigger.
  // Gating on `actionTools` alone would leave that toggle with no way to reach it.
  if (actionTools.length === 0 && !showDeepResearch) return null;

  function close() {
    setOpen(false);
    setShowSources(false);
  }

  return (
    <>
      <Button
        prominence="tertiary"
        icon={SvgSliders}
        accessibilityLabel="Manage Actions"
        onPress={() => {
          // A raised keyboard covers the bottom of the sheet, which rises from the same edge.
          Keyboard.dismiss();
          setShowSources(false);
          setOpen(true);
        }}
      />

      <Sheet
        visible={open}
        onClose={close}
        title={showSources ? "Sources" : "Actions"}
        onBack={showSources ? () => setShowSources(false) : undefined}
      >
        <ScrollView
          style={{ maxHeight: MAX_LIST_HEIGHT }}
          keyboardShouldPersistTaps="handled"
          contentContainerClassName="pb-8"
        >
          {showSources ? (
            <SourceSwitchList />
          ) : (
            <>
              {/* Deep research is a mode, not a tool: nothing to force or disable, so it renders
                  as a plain switch rather than an ActionLineItem. Web keeps it as a composer
                  pill instead. */}
              {showDeepResearch ? (
                <LineItemButton
                  icon={SvgHourglass}
                  title="Deep Research"
                  titleMaxLines={1}
                  sizePreset="main-ui"
                  variant="section"
                  onPress={toggleDeepResearch}
                  rightChildren={
                    <Switch
                      checked={deepResearchEnabled}
                      onCheckedChange={toggleDeepResearch}
                      accessibilityLabel="Toggle Deep Research"
                    />
                  }
                />
              ) : null}

              {actionTools.map((tool) => (
                <ActionLineItem
                  key={tool.id}
                  tool={tool}
                  isForced={forcedToolId === tool.id}
                  isDisabled={disabledToolIds.includes(tool.id)}
                  isUnavailable={unavailableToolIds.includes(tool.id)}
                  sourceCounts={
                    tool.id === sourceToolId && sourceOptions.length > 0
                      ? {
                          enabled: enabledSourceCount,
                          total: sourceOptions.length,
                        }
                      : null
                  }
                  onForceToggle={() => toggleForcedTool(tool.id)}
                  onToggleEnabled={() => toggleToolEnabled(tool.id)}
                  onOpenSources={() => setShowSources(true)}
                  onClose={close}
                />
              ))}
            </>
          )}
        </ScrollView>
      </Sheet>
    </>
  );
}
