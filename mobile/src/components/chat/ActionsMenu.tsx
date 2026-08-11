/*
 * A bottom sheet, not web's trigger-anchored popover: the mobile composer is keyboard-sticky, so
 * an anchored panel would chase a moving anchor.
 */
import { useState } from "react";
import { Keyboard, ScrollView } from "react-native";

import { ActionLineItem } from "@/components/chat/ActionLineItem";
import { SourceSwitchList } from "@/components/chat/SourceSwitchList";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { useComposerTools } from "@/state/ComposerToolsProvider";
import SvgSliders from "@/icons/sliders";

const MAX_LIST_HEIGHT = 420;

export function ActionsMenu() {
  const {
    actionTools,
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

  if (actionTools.length === 0) return null;

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
            actionTools.map((tool) => (
              <ActionLineItem
                key={tool.id}
                tool={tool}
                isForced={forcedToolId === tool.id}
                isDisabled={disabledToolIds.includes(tool.id)}
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
            ))
          )}
        </ScrollView>
      </Sheet>
    </>
  );
}
