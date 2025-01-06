"use effect";
import { useContext } from "react";
import { FiSidebar } from "react-icons/fi";
import { SettingsContext } from "../settings/SettingsProvider";
import { NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA } from "@/lib/constants";
import { LeftToLineIcon, NewChatIcon, RightToLineIcon } from "../icons/icons";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { pageType } from "@/app/chat/sessionSidebar/types";
import { Logo } from "../logo/Logo";
import Link from "next/link";
import { LogoComponent } from "@/app/chat/shared_chat_search/FixedLogo";

export default function LogoWithText({
  toggleSidebar,
  hideOnMobile,
  handleNewChat,
  page,
  toggled,
  showArrow,
  assistantId,
  explicitlyUntoggle = () => null,
}: {
  hideOnMobile?: boolean;
  toggleSidebar?: () => void;
  handleNewChat?: () => void;
  page: pageType;
  toggled?: boolean;
  showArrow?: boolean;
  assistantId?: number;
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
        <button
          onClick={() => toggleSidebar()}
          className="flex gap-x-2 items-center ml-0  desktop:hidden "
        >
          {!toggled ? (
            <Logo className="desktop:hidden -my-2" height={24} width={24} />
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
        </button>
      ) : (
        <div className="mr-1 invisible mb-auto h-6 w-6">
          <Logo height={24} width={24} />
        </div>
      )}

      {!toggled && (
        <div
          className={`${
            showArrow ? "desktop:hidden" : "invisible"
          } break-words inline-block w-fit text-text-700 text-xl`}
        >
          <LogoComponent
            enterpriseSettings={enterpriseSettings!}
            backgroundToggled={toggled}
          />
        </div>
      )}
      {page == "chat" && !showArrow && (
        <TooltipProvider delayDuration={1000}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Link
                className="my-auto mobile:hidden"
                href={
                  `/${page}` +
                  (NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA && assistantId
                    ? `?assistantId=${assistantId}`
                    : "")
                }
                onClick={(e) => {
                  if (e.metaKey || e.ctrlKey) {
                    return;
                  }
                  if (handleNewChat) {
                    handleNewChat();
                  }
                }}
              >
                <NewChatIcon
                  className="ml-2 flex-none text-text-700 hover:text-text-600 transition-colors duration-300"
                  size={20}
                />
              </Link>
            </TooltipTrigger>
            <TooltipContent>New Chat</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}

      {showArrow && toggleSidebar && (
        <TooltipProvider delayDuration={0}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                className="mr-3 my-auto ml-auto"
                onClick={() => {
                  toggleSidebar();
                  if (toggled) {
                    explicitlyUntoggle();
                  }
                }}
              >
                {!toggled && !combinedSettings?.isMobile ? (
                  <RightToLineIcon className="mobile:hidden text-sidebar-toggle" />
                ) : (
                  <LeftToLineIcon className="mobile:hidden text-sidebar-toggle" />
                )}
                <FiSidebar
                  size={20}
                  className="hidden mobile:block text-text-mobile-sidebar"
                />
              </button>
            </TooltipTrigger>
            <TooltipContent>
              {toggled ? `Unpin sidebar` : "Pin sidebar"}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}
    </div>
  );
}
