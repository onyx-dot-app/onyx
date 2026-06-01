// IoBlockLabel.tsx — small "Request" / "Response" label.
//
// Native mirror of web IoBlockLabel. Used by tool renderers that show a paired
// input/output (e.g. CustomTool, CodingAgent's bash step).

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
