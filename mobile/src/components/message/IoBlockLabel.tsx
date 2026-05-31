// IoBlockLabel.tsx — small "Request" / "Response" label.
//
// Ported from web:
//   web/src/app/app/message/messageComponents/IoBlockLabel.tsx
// Used by tool renderers that show a paired input/output (e.g. CustomTool,
// CodingAgent's bash step). Arrow-exchange icon + secondary-body label.
// Web `flex items-center gap-1` -> RN row with a 4px gap.

import { View } from "react-native";

import { SvgArrowExchange } from "@/components/icons";
import { Text } from "@/components/opal";

interface IoBlockLabelProps {
  label: string;
}

export function IoBlockLabel({ label }: IoBlockLabelProps) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
      <SvgArrowExchange size={12} color="text-02" />
      <Text font="secondary-body" color="text-04">
        {label}
      </Text>
    </View>
  );
}

export default IoBlockLabel;
