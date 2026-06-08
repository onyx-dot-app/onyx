// Horizontal tool-pill tab strip shared by ParallelStreamingHeader and
// ParallelTimelineTabs.

import { Pressable, ScrollView, type ViewStyle } from "react-native";

import { Text, Spinner } from "@/components/opal";
import { useThemeColors } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import { TimelineIcon } from "@/components/message/timeline/toolIcon";
import type { TransformedStep } from "@/state/timeline/transformers";
import {
  getToolName,
  getToolIconName,
  isToolComplete,
} from "@/state/timeline/toolDisplayHelpers";

export interface TimelinePillTabsProps {
  steps: TransformedStep[];
  activeKey: string;
  onSelect: (key: string) => void;
  /** Whether a given step shows the spinner instead of its tool icon. */
  loadingPredicate?: (step: TransformedStep) => boolean;
  style?: ViewStyle;
}

export function TimelinePillTabs({
  steps,
  activeKey,
  onSelect,
  loadingPredicate = (step) => !isToolComplete(step.packets),
  style,
}: TimelinePillTabsProps) {
  const colors = useThemeColors();

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={{ alignItems: "center", gap: 6, paddingHorizontal: 4 }}
      style={style}
    >
      {steps.map((step) => {
        const active = step.key === activeKey;
        const loading = loadingPredicate(step);
        return (
          <Pressable
            key={step.key}
            onPress={() => onSelect(step.key)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 4,
              paddingHorizontal: 8,
              paddingVertical: 4,
              borderRadius: radii["08"],
              backgroundColor: active
                ? colors["background-tint-02"]
                : "transparent",
            }}
          >
            {loading ? (
              <Spinner size={12} color="text-03" />
            ) : (
              <TimelineIcon
                name={getToolIconName(step.packets)}
                size={12}
                color={active ? "text-04" : "text-02"}
              />
            )}
            <Text font="main-ui-muted" color={active ? "text-04" : "text-03"}>
              {getToolName(step.packets)}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

export default TimelinePillTabs;
