// ParallelStreamingHeader.tsx — horizontal tool-pill tabs (per-tab spinner +
// active styling) + fold control, shown while parallel tools stream collapsed.
// Ports web ParallelStreamingHeader (Opal pill Tabs -> horizontal ScrollView).

import { memo } from "react";
import { View, Pressable, ScrollView } from "react-native";

import { Text, Spinner } from "@/components/opal";
import { useThemeColors } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import { TimelineIcon } from "@/components/message/timeline/toolIcon";
import { HeaderToggle } from "@/components/message/timeline/headers/HeaderToggle";
import type { TransformedStep } from "@/state/timeline/transformers";
import {
  getToolName,
  getToolIconName,
  isToolComplete,
} from "@/state/timeline/toolDisplayHelpers";

export interface ParallelStreamingHeaderProps {
  steps: TransformedStep[];
  activeTab: string;
  onTabChange: (key: string) => void;
  collapsible: boolean;
  isExpanded: boolean;
  onToggle: () => void;
}

export const ParallelStreamingHeader = memo(function ParallelStreamingHeader({
  steps,
  activeTab,
  onTabChange,
  collapsible,
  isExpanded,
  onToggle,
}: ParallelStreamingHeaderProps) {
  const colors = useThemeColors();

  return (
    <View
      style={{
        flex: 1,
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
      }}
    >
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ alignItems: "center", gap: 6, paddingHorizontal: 4 }}
        style={{ flex: 1 }}
      >
        {steps.map((step) => {
          const active = step.key === activeTab;
          const loading = !isToolComplete(step.packets);
          return (
            <Pressable
              key={step.key}
              onPress={() => onTabChange(step.key)}
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

      {collapsible && (
        <HeaderToggle isExpanded={isExpanded} onToggle={onToggle} />
      )}
    </View>
  );
});

export default ParallelStreamingHeader;
