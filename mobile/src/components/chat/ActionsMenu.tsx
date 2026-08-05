// The composer's actions menu — force a tool, enable/disable a tool. RN port of
// web/src/refresh-components/popovers/ActionsPopover/index.tsx. Named for the menu, not its
// container: the container is deliberately swappable (see components/ui/sheet.tsx).
import { useState } from "react";
import { Keyboard, ScrollView } from "react-native";

import { ActionLineItem } from "@/components/chat/ActionLineItem";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { useComposerTools } from "@/state/ComposerToolsProvider";
import SvgSliders from "@/icons/sliders";

// Caps the list height; an agent rarely has enough tools to reach it.
const MAX_LIST_HEIGHT = 420;

export function ActionsMenu() {
  const {
    actionTools,
    forcedToolId,
    toggleForcedTool,
    disabledToolIds,
    toggleToolEnabled,
  } = useComposerTools();
  const [open, setOpen] = useState(false);

  if (actionTools.length === 0) return null;

  return (
    <>
      <Button
        prominence="tertiary"
        icon={SvgSliders}
        accessibilityLabel="Manage Actions"
        onPress={() => {
          // The sheet slides up from the same edge the keyboard occupies; leaving it raised
          // covers the bottom of the list.
          Keyboard.dismiss();
          setOpen(true);
        }}
      />

      <Sheet visible={open} onClose={() => setOpen(false)} title="Actions">
        <ScrollView
          style={{ maxHeight: MAX_LIST_HEIGHT }}
          keyboardShouldPersistTaps="handled"
          contentContainerClassName="pb-8"
        >
          {actionTools.map((tool) => (
            <ActionLineItem
              key={tool.id}
              tool={tool}
              isForced={forcedToolId === tool.id}
              isDisabled={disabledToolIds.includes(tool.id)}
              onForceToggle={() => toggleForcedTool(tool.id)}
              onToggleEnabled={() => toggleToolEnabled(tool.id)}
              onClose={() => setOpen(false)}
            />
          ))}
        </ScrollView>
      </Sheet>
    </>
  );
}
