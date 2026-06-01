// Native mirror of web ParallelStreamingHeader (pill Tabs -> horizontal ScrollView).

import { memo } from "react";
import { View } from "react-native";

import { HeaderToggle } from "@/components/message/timeline/headers/HeaderToggle";
import { TimelinePillTabs } from "@/components/message/timeline/primitives/TimelinePillTabs";
import type { TransformedStep } from "@/state/timeline/transformers";
import { isToolComplete } from "@/state/timeline/toolDisplayHelpers";

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
  return (
    <View
      style={{
        flex: 1,
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
      }}
    >
      <TimelinePillTabs
        steps={steps}
        activeKey={activeTab}
        onSelect={onTabChange}
        loadingPredicate={(step) => !isToolComplete(step.packets)}
        style={{ flex: 1 }}
      />

      {collapsible && (
        <HeaderToggle isExpanded={isExpanded} onToggle={onToggle} />
      )}
    </View>
  );
});

export default ParallelStreamingHeader;
