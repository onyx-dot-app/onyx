"use client";

import React, { useContext } from "react";
import { usePathname } from "next/navigation";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { CgArrowsExpandUpLeft } from "react-icons/cg";
import { LogoComponent } from "@/components/logo/FixedLogo";
import Text from "@/components-2/Text";
import { SidebarButton, SidebarSection } from "@/sections/sidebar/components";
import Settings from "@/sections/sidebar/Settings";

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

export function AdminSidebar({ collections }: AdminSidebarProps) {
  const combinedSettings = useContext(SettingsContext);
  const pathname = usePathname() ?? "";
  if (!combinedSettings) {
    return null;
  }

  return (
    <div className="flex flex-col justify-between h-full !min-w-[15rem] py-padding-content px-padding-button bg-background-tint-02 gap-padding-content">
      <LogoComponent
        show={true}
        enterpriseSettings={combinedSettings.enterpriseSettings!}
        backgroundToggled={false}
        isAdmin={true}
      />

      <SidebarButton
        icon={() => <CgArrowsExpandUpLeft className="text-text-03" size={28} />}
        href="/chat"
      >
        Exit Admin
      </SidebarButton>

      <div className="relative flex flex-col flex-1 overflow-y-auto gap-padding-content">
        {collections.map((collection, index) => (
          <SidebarSection key={index} title={collection.name}>
            <div className="flex flex-col w-full">
              {collection.items.map(({ link, icon: Icon, name }, index) => (
                <SidebarButton
                  key={index}
                  href={link}
                  active={pathname.startsWith(link)}
                  icon={() => <Icon className="text-text-03" size={28} />}
                >
                  {name}
                </SidebarButton>
              ))}
            </div>
          </SidebarSection>
        ))}
      </div>
      <div className="flex flex-col gap-spacing-interline">
        <Settings removeAdminPanelLink />
        {combinedSettings.webVersion && (
          <Text text02 className="px-padding-button">
            Onyx version: {combinedSettings.webVersion}
          </Text>
        )}
      </div>
    </div>
  );
}
