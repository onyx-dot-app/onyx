// The input bar's left-cluster controls, mirroring web's `chatControls` block
// (web/src/sections/input/AppInputBar.tsx).
import { View } from "react-native";

import { SelectButton } from "@/components/ui/select-button";
import { useComposerTools } from "@/state/ComposerToolsProvider";
import SvgHourglass from "@/icons/hourglass";

export function ToolbarControls() {
  const { showDeepResearch, deepResearchEnabled, toggleDeepResearch } =
    useComposerTools();

  if (!showDeepResearch) return null;

  // Wrapper: `SelectButton`'s `self-start` would top-align the 28px pill against the 36px
  // paperclip; hugging it here keeps the row centered.
  return (
    <View className="flex-row items-center">
      <SelectButton
        icon={SvgHourglass}
        state={deepResearchEnabled ? "selected" : "empty"}
        // folded = label hidden
        foldable={!deepResearchEnabled}
        onPress={toggleDeepResearch}
        accessibilityLabel="Deep Research"
      >
        Deep Research
      </SelectButton>
    </View>
  );
}
