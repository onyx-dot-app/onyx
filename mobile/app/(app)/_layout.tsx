import { Tabs } from "expo-router";
import { Text } from "react-native";

import { useToken } from "@/theme/ThemeProvider";

// Authenticated flow group. Owns the primary navigation.
//
// OPEN DECISION (doc 04): bottom tabs vs. drawer for the (app) primary nav.
// Web uses a sidebar; phones-first leans tabs, so this ships a reasonable
// default of bottom Tabs — NOT locked. Swap to a drawer here if that wins.
//
// No icon library is installed, so tab "icons" are simple emoji glyphs. They
// can be replaced with a real icon set (or removed) later — do not add a dep.
export default function AppLayout() {
  const activeColor = useToken("text-05");
  const inactiveColor = useToken("text-03");

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: activeColor,
        tabBarInactiveTintColor: inactiveColor,
      }}
    >
      <Tabs.Screen
        name="(chat)"
        options={{
          title: "Chat",
          tabBarIcon: ({ color }) => <Text style={{ color }}>💬</Text>,
        }}
      />
      <Tabs.Screen
        name="search"
        options={{
          title: "Search",
          tabBarIcon: ({ color }) => <Text style={{ color }}>🔍</Text>,
        }}
      />
      <Tabs.Screen
        name="assistants"
        options={{
          title: "Assistants",
          tabBarIcon: ({ color }) => <Text style={{ color }}>🤖</Text>,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: "Settings",
          tabBarIcon: ({ color }) => <Text style={{ color }}>⚙️</Text>,
        }}
      />
    </Tabs>
  );
}
