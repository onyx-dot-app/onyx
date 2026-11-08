// The input bar's left-cluster controls, mirroring web's `chatControls` block
// (web/src/sections/input/AppInputBar.tsx).
import { View } from "react-native";

import { ActionsMenu } from "@/components/chat/ActionsMenu";
import { SelectButton } from "@/components/ui/select-button";
import { getIconForToolId } from "@/chat/tools";
import { useComposerTools } from "@/state/ComposerToolsProvider";

// Sized so the actions trigger on this side, and the model pill and send button on the other,
// still fit on the narrowest supported phone.
const PREFERRED_PILL_MAX_WIDTH = 132;

export function ToolbarControls() {
  const { actionTools, preferredToolId, togglePreferredTool, disabledToolIds } =
    useComposerTools();

  // A preferred tool that is switched off is never sent, so its pill would advertise a control the
  // request ignores.
  const preferredTool = actionTools.find(
    (tool) => tool.id === preferredToolId && !disabledToolIds.includes(tool.id),
  );

  return (
    <View className="min-w-0 shrink flex-row items-center gap-8">
      <ActionsMenu />

      {/* Kept outside the menu, as web does, so the force can be released in one tap. Capped
          because Yoga defaults flexShrink to 0: a long tool name would otherwise push the send
          button off the composer card. */}
      {preferredTool ? (
        <View className="shrink" style={{ maxWidth: PREFERRED_PILL_MAX_WIDTH }}>
          <SelectButton
            icon={getIconForToolId(preferredTool.in_code_tool_id)}
            state="selected"
            onPress={() => togglePreferredTool(preferredTool.id)}
            accessibilityLabel={`${preferredTool.display_name || preferredTool.name} (preferred)`}
          >
            {preferredTool.display_name || preferredTool.name}
          </SelectButton>
        </View>
      ) : null}
    </View>
  );
}
