"use client";

import React, { useContext } from "react";
import { usePathname } from "next/navigation";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { CgArrowsExpandUpLeft } from "react-icons/cg";
import { LogoComponent } from "@/components/logo/FixedLogo";
import Text from "@/refresh-components/Text";
import { SidebarSection } from "@/sections/sidebar/components";
import Settings from "@/sections/sidebar/Settings";
import NavigationTab from "@/refresh-components/buttons/NavigationTab";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";

interface Item {
  name: string;
  icon: React.ComponentType<any>;
  link: string;
  error?: boolean;
}

interface Collection {
  name: string;
  items: Item[];
}

interface AdminSidebarProps {
  collections: Collection[];
}

export default function AdminSidebar({ collections }: AdminSidebarProps) {
  const combinedSettings = useContext(SettingsContext);
  const pathname = usePathname() ?? "";
  if (!combinedSettings) {
    return null;
  }

  return (
    <SidebarWrapper>
      <LogoComponent
        show={true}
        enterpriseSettings={combinedSettings.enterpriseSettings!}
        backgroundToggled={false}
        isAdmin={true}
      />

      <NavigationTab
        icon={({ className }) => (
          <CgArrowsExpandUpLeft className={className} size={16} />
        )}
        href="/chat"
      >
        Exit Admin
      </NavigationTab>

      <div className="flex flex-col flex-1 overflow-y-auto gap-padding-content">
        {collections.map((collection, index) => (
          <SidebarSection key={index} title={collection.name}>
            <div className="flex flex-col w-full">
              {collection.items.map(({ link, icon: Icon, name }, index) => (
                <NavigationTab
                  key={index}
                  href={link}
                  active={pathname.startsWith(link)}
                  icon={({ className }) => (
                    <Icon className={className} size={16} />
                  )}
                >
                  {name}
                </NavigationTab>
              ))}
            </div>
          </SidebarSection>
        ))}
      </div>
      <div className="flex flex-col gap-spacing-interline">
        {combinedSettings.webVersion && (
          <Text text02 secondaryBody className="px-spacing-interline">
            Onyx version: {combinedSettings.webVersion}
          </Text>
        )}
        <Settings removeAdminPanelLink />
      </div>
    </SidebarWrapper>
  );
}
