import { ReactNode } from "react";
import { SvgProps } from "@/icons";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";

export interface StepSidebarProps {
  children: ReactNode;
  buttonName: string;
  buttonIcon: React.FunctionComponent<SvgProps>;
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
      <div className="px-spacing-interline">
        <SidebarTab
          leftIcon={buttonIcon}
          className="bg-background-tint-00"
          href={buttonHref}
        >
          {buttonName}
        </SidebarTab>
      </div>

      <div className="h-full w-full px-spacing-paragraph">{children}</div>
    </SidebarWrapper>
  );
}
