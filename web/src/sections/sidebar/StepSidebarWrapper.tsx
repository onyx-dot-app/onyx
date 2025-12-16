import { ReactNode } from "react";
import type { IconProps } from "@opal";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";

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
  return (
    <SidebarWrapper>
      <div className="px-2">
        <SidebarTab
          leftIcon={buttonIcon}
          className="bg-background-tint-00"
          href={buttonHref}
        >
          {buttonName}
        </SidebarTab>
      </div>

      <div className="h-full w-full px-4">{children}</div>
    </SidebarWrapper>
  );
}
