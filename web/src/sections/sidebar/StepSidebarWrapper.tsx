import { SettingsContext } from "@/components/settings/SettingsProvider";
import { useContext, ReactNode } from "react";
import { LogoComponent } from "@/components/logo/FixedLogo";
import { SvgProps } from "@/icons";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";

interface StepSidebarProps {
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
  const combinedSettings = useContext(SettingsContext);
  if (!combinedSettings) {
    return null;
  }

  const enterpriseSettings = combinedSettings.enterpriseSettings;

  return (
    <div className="fixed left-0 top-0 flex flex-col h-screen w-[15rem] bg-background-tint-02 py-padding-content px-padding-button gap-padding-content z-10">
      <div className="flex flex-col items-start justify-center">
        <LogoComponent enterpriseSettings={enterpriseSettings} />
      </div>

      <SidebarTab
        leftIcon={buttonIcon}
        className="bg-background-tint-00"
        href={buttonHref}
      >
        {buttonName}
      </SidebarTab>

      <div className="h-full flex">
        <div className="w-full px-2">{children}</div>
      </div>
    </div>
  );
}
