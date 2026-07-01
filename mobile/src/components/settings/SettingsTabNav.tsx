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
      {tabs.map((tab) => (
        <SidebarTab
          key={String(tab.href)}
          href={tab.href}
          selected={tab.href === activeHref}
        >
          {tab.label}
        </SidebarTab>
      ))}
    </View>
  );
}

export { SettingsTabNav, type SettingsTabNavProps };
