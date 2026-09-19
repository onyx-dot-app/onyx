import { View } from "react-native";

import { cn } from "@/lib/utils";
// Leaf import (not the barrel) keeps this reanimated-free / unit-testable.
import { SidebarTab } from "@/components/sidebar/SidebarTab";
import type { SettingsTab } from "@/components/settings/interfaces";

// A phone renders the vertical `SidebarTab` column (web's `md:` layout), not the
// narrow-screen dropdown.
interface SettingsTabNavProps {
  tabs: SettingsTab[];
  activeHref: string;
  className?: string;
}

function SettingsTabNav({ tabs, activeHref, className }: SettingsTabNavProps) {
  return (
    <View className={cn("flex-col px-8", className)}>
      {tabs.map((tab) => {
        // Reduce a bare-path or object-form href to its pathname to match
        // `activeHref` (a `usePathname()` string) and to key the list.
        const path =
          typeof tab.href === "string" ? tab.href : tab.href.pathname;
        return (
          <SidebarTab key={path} href={tab.href} selected={path === activeHref}>
            {tab.label}
          </SidebarTab>
        );
      })}
    </View>
  );
}

export { SettingsTabNav, type SettingsTabNavProps };
