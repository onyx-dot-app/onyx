// The input bar's left-cluster controls, mirroring web's `chatControls` block
// (web/src/sections/input/AppInputBar.tsx).
import { View } from "react-native";

import { ActionsMenu } from "@/components/chat/ActionsMenu";
import { SelectButton } from "@/components/ui/select-button";
import { getIconForToolId } from "@/chat/tools";
import { useComposerTools } from "@/state/ComposerToolsProvider";

// Sized so the actions trigger on this side, and the model pill and send button on the other,
// still fit on the narrowest supported phone.
const FORCED_PILL_MAX_WIDTH = 132;

export function ToolbarControls() {
  const { actionTools, forcedToolId, toggleForcedTool, disabledToolIds } =
    useComposerTools();

  // A forced tool that is switched off is never sent, so its pill would advertise a control the
  // request ignores.
  const forcedTool = actionTools.find(
    (tool) => tool.id === forcedToolId && !disabledToolIds.includes(tool.id),
  );

  return (
    <View className="min-w-0 shrink flex-row items-center gap-8">
      <ActionsMenu />

      {/* Kept outside the menu, as web does, so the force can be released in one tap. Capped
          because Yoga defaults flexShrink to 0: a long tool name would otherwise push the send
          button off the composer card. */}
      {forcedTool ? (
        <View className="shrink" style={{ maxWidth: FORCED_PILL_MAX_WIDTH }}>
          <SelectButton
            icon={getIconForToolId(forcedTool.in_code_tool_id)}
            state="selected"
            onPress={() => toggleForcedTool(forcedTool.id)}
            accessibilityLabel={`${forcedTool.display_name || forcedTool.name} (forced)`}
          >
            {forcedTool.display_name || forcedTool.name}
          </SelectButton>
        </View>
      ) : null}
    </View>
  );
}
