import { useState } from "react";
import { Pressable, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import { SidebarLayouts, SidebarTab, useSidebar } from "@/components/sidebar";
import SvgSidebar from "@/icons/sidebar";
import SvgBubbleText from "@/icons/bubble-text";
import SvgSearch from "@/icons/search";
import SvgFolder from "@/icons/folder";
import SvgPlus from "@/icons/plus";
import SvgSettings from "@/icons/settings";

// Demo of the React Native Sidebar — a port of the web Opal `SidebarLayouts` shell.
// Tap the menu icon to slide the sidebar in over the screen; tap the backdrop or
// swipe left to close. Colors resolve from @onyx-ai/shared, identical to web in
// both light and dark.

function SidebarTrigger() {
  const { setFolded } = useSidebar();
  return (
    <Pressable
      onPress={() => setFolded(false)}
      hitSlop={8}
      className="rounded-08 p-2 active:bg-background-tint-03"
    >
      <Icon as={SvgSidebar} size={24} className="text-text-04" />
    </Pressable>
  );
}

export default function Home() {
  const { setFolded } = useSidebar();
  const [selected, setSelected] = useState("general");

  function choose(key: string) {
    setSelected(key);
    setFolded(true); // auto-dismiss after selection (demo behavior)
  }

  return (
    <SafeAreaView className="flex-1 bg-background-neutral-00">
      <View className="flex-row items-center gap-2 px-4 py-3">
        <SidebarTrigger />
        <Text font="main-ui-action">Onyx Mobile</Text>
      </View>

      <View className="flex-1 items-center justify-center px-6">
        <Text font="main-content-body" className="text-center text-text-03">
          Tap the menu icon to open the sidebar. Tap the backdrop or swipe left
          to close.
        </Text>
      </View>

      <SidebarLayouts.Root foldable>
        <SidebarLayouts.Header
          logo={() => (
            <Text font="heading-h3" className="px-1">
              Onyx
            </Text>
          )}
        />

        <SidebarLayouts.Body scrollKey="demo">
          <SidebarLayouts.Section title="Chats">
            <SidebarTab
              icon={SvgBubbleText}
              selected={selected === "general"}
              onPress={() => choose("general")}
            >
              General
            </SidebarTab>
            <SidebarTab
              icon={SvgSearch}
              selected={selected === "search"}
              onPress={() => choose("search")}
            >
              Search
            </SidebarTab>
          </SidebarLayouts.Section>

          <SidebarLayouts.Section
            title="Projects"
            action={
              <Pressable
                hitSlop={8}
                className="rounded-08 p-1 active:bg-background-tint-03"
              >
                <Icon as={SvgPlus} size={16} className="text-text-03" />
              </Pressable>
            }
          >
            <SidebarTab
              icon={SvgFolder}
              selected={selected === "onboarding"}
              onPress={() => choose("onboarding")}
              rightChildren={
                <Text font="secondary-body" className="text-text-03">
                  3
                </Text>
              }
            >
              Onboarding
            </SidebarTab>
            <SidebarTab
              nested
              selected={selected === "spec"}
              onPress={() => choose("spec")}
            >
              Spec draft
            </SidebarTab>
          </SidebarLayouts.Section>
        </SidebarLayouts.Body>

        <SidebarLayouts.Footer>
          <SidebarTab
            icon={SvgSettings}
            variant="sidebar-light"
            selected={selected === "settings"}
            onPress={() => choose("settings")}
          >
            Settings
          </SidebarTab>
        </SidebarLayouts.Footer>
      </SidebarLayouts.Root>
    </SafeAreaView>
  );
}
