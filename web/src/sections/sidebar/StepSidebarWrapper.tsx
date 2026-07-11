"use client";

import { ReactNode } from "react";
import type { IconProps } from "@opal/types";
import { SidebarLayouts } from "@opal/layouts";
import { SidebarTab } from "@opal/components";
import { renderAppLogo } from "@/lib/app/utils";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";

export interface StepSidebarProps {
  children: ReactNode;
  buttonName: string;
  buttonIcon: React.FunctionComponent<IconProps>;
  buttonHref: string;
}

export default function StepSidebar({
  children,
  buttonName,
  buttonIcon,
  buttonHref,
}: StepSidebarProps) {
  const showLogoWhenFolded = useShowLogoWhenFolded();

  return (
    <SidebarLayouts.Root>
      <SidebarLayouts.Header
        renderAppLogo={renderAppLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      >
        <SidebarTab icon={buttonIcon} href={buttonHref}>
          {buttonName}
        </SidebarTab>
      </SidebarLayouts.Header>
      <SidebarLayouts.Body scrollKey="step-sidebar">
        {children}
      </SidebarLayouts.Body>
    </SidebarLayouts.Root>
  );
}
