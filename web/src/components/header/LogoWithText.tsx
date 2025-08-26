"use effect";
import { useContext } from "react";
import { FiSidebar } from "react-icons/fi";
import { SettingsContext } from "../settings/SettingsProvider";
import { pageType } from "@/components/sidebar/types";
import { Logo } from "../logo/Logo";
import { LogoComponent } from "@/components/logo/FixedLogo";

export default function LogoWithText({
  toggleSidebar,
  hideOnMobile,
  page,
  toggled,
  showArrow,
  explicitlyUntoggle = () => null,
}: {
  hideOnMobile?: boolean;
  toggleSidebar?: () => void;
  page: pageType;
  toggled?: boolean;
  showArrow?: boolean;
  explicitlyUntoggle?: () => void;
}) {
  const combinedSettings = useContext(SettingsContext);
  const enterpriseSettings = combinedSettings?.enterpriseSettings;
  return (
    <div
      className={`${
        hideOnMobile && "mobile:hidden"
      } z-[100] ml-2 mt-1 h-8 mb-auto shrink-0 flex gap-x-0 items-center text-xl`}
    >
      {toggleSidebar && page == "chat" ? (
        <div
          onClick={() => toggleSidebar()}
          className="flex gap-x-2 items-center ml-0 cursor-pointer desktop:hidden "
        >
          {!toggled ? (
            <Logo className="desktop:hidden" height={24} width={24} />
          ) : (
            <LogoComponent
              show={toggled}
              enterpriseSettings={enterpriseSettings!}
              backgroundToggled={toggled}
            />
          )}

          <FiSidebar
            size={20}
            className={`text-text-mobile-sidebar desktop:hidden ${
              toggled && "mobile:hidden"
            }`}
          />
        </div>
      ) : (
        <div className="mr-1 invisible mb-auto h-6 w-6">
          <Logo height={24} width={24} />
        </div>
      )}

      {!toggled && (
        <div
          className={`${
            showArrow ? "desktop:hidden" : "invisible"
          } break-words inline-block w-fit text-text-700 dark:text-neutral-300 text-xl`}
        >
          <LogoComponent
            enterpriseSettings={enterpriseSettings!}
            backgroundToggled={toggled}
          />
        </div>
      )}
      <div className="flex ml-auto gap-x-4"></div>
    </div>
  );
}
