"use client";

import { useTranslations } from "next-intl";
import { SidebarTab } from "@opal/components";
import { SidebarLayouts } from "@opal/layouts";
import { useNavigation, usePathname } from "@opal/navigation";
import { SvgBlocks, SvgLink, SvgPlug } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import {
  CUSTOMIZE_TABS,
  customizeTabHref,
  type CustomizeTab,
} from "@/lib/customize/paths";

const TAB_ICONS = {
  skills: SvgBlocks,
  integrations: SvgLink,
  plugins: SvgPlug,
} satisfies Record<CustomizeTab, IconFunctionComponent>;

/** The Customize window: one tab per Customize list. */
export default function CustomizeSidebarContent() {
  const t = useTranslations("customize");
  const navigation = useNavigation();
  const pathname = usePathname();
  return (
    <SidebarLayouts.Body scrollKey="customize-sidebar">
      <SidebarLayouts.Section>
        {CUSTOMIZE_TABS.map((tab) => {
          const href = customizeTabHref(tab);
          return (
            <SidebarTab
              key={tab}
              icon={TAB_ICONS[tab]}
              {...navigation.linkTo(href, { scroll: false })}
              selected={pathname === href || pathname.startsWith(`${href}/`)}
            >
              {t(`tabs.${tab}`)}
            </SidebarTab>
          );
        })}
      </SidebarLayouts.Section>
    </SidebarLayouts.Body>
  );
}
