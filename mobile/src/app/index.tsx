import { Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

// Placeholder home screen (foundation). Replaced by the real chat-first UI in later phases
// (see docs/plans/2026-05-30-mobile-app/05-ui-component-layer.md and 06-state-and-data.md).
export default function Index() {
  return (
    <SafeAreaView style={{ flex: 1 }}>
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: 8 }}>
        <Text style={{ fontSize: 18, fontWeight: "600" }}>Onyx Mobile</Text>
        <Text style={{ opacity: 0.6 }}>Foundation · Phase 0</Text>
      </View>
    </SafeAreaView>
  );
}
