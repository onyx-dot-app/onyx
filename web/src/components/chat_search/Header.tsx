"use client";
import { UserDropdown } from "../UserDropdown";
import { FiShare2 } from "react-icons/fi";
import { SetStateAction, useContext, useEffect } from "react";
import { NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA } from "@/lib/constants";
import { ChatSession } from "@/app/chat/interfaces";
import Link from "next/link";
import { pageType } from "@/app/chat/sessionSidebar/types";
import { useRouter } from "next/navigation";
import { ChatBanner } from "@/app/chat/ChatBanner";
import LogoWithText from "../header/LogoWithText";
import { NewChatIcon } from "../icons/icons";
import { SettingsContext } from "../settings/SettingsProvider";

export default function FunctionalHeader({
  page,
  currentChatSession,
  setSharingModalVisible,
  toggleSidebar = () => null,
  reset = () => null,
  sidebarToggled,
  documentSidebarToggled,
  toggleUserSettings,
  hideUserDropdown,
}: {
  reset?: () => void;
  page: pageType;
  sidebarToggled?: boolean;
  documentSidebarToggled?: boolean;
  currentChatSession?: ChatSession | null | undefined;
  setSharingModalVisible?: (value: SetStateAction<boolean>) => void;
  toggleSidebar?: () => void;
  toggleUserSettings?: () => void;
  hideUserDropdown?: boolean;
}) {
  const settings = useContext(SettingsContext);
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey) {
        switch (event.key.toLowerCase()) {
          case "u":
            event.preventDefault();
            window.open(
              `/${page}` +
                (NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA &&
                currentChatSession
                  ? `?assistantId=${currentChatSession.persona_id}`
                  : ""),
              "_self"
            );
            break;
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [page, currentChatSession]);
  const router = useRouter();

  const handleNewChat = () => {
    reset();
    const newChatUrl =
      `/${page}` +
      (NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA && currentChatSession
        ? `?assistantId=${currentChatSession.persona_id}`
        : "");
    router.push(newChatUrl);
  };
  return (
    <div className="left-0 sticky top-0 z-20 w-full relative flex">
      <div className="items-end flex mt-2 cursor-pointer text-text-700 relative flex w-full">
        <LogoWithText
          assistantId={currentChatSession?.persona_id}
          page={page}
          toggleSidebar={toggleSidebar}
          toggled={sidebarToggled && !settings?.isMobile}
          handleNewChat={handleNewChat}
        />
        <div className="mt-2 flex w-full h-8">
          <div
            style={{ transition: "width 0.30s ease-out" }}
            className={`
            mobile:hidden
            flex-none 
            mx-auto
            overflow-y-hidden 
            transition-all 
            duration-300 
            ease-in-out
            h-full
            ${sidebarToggled ? "w-[250px]" : "w-[0px]"}
            `}
          />

          <div className="w-full mobile:-mx-20 desktop:px-4">
            <ChatBanner />
          </div>

          <div className="invisible">
            <LogoWithText
              page={page}
              toggled={sidebarToggled}
              toggleSidebar={toggleSidebar}
              handleNewChat={handleNewChat}
            />
          </div>

          <div className="absolute right-0 mobile:top-2 desktop:top-0 flex">
            {setSharingModalVisible && !hideUserDropdown && (
              <div
                onClick={() => setSharingModalVisible(true)}
                className="mobile:hidden mr-2 my-auto rounded cursor-pointer hover:bg-hover-light"
              >
                <FiShare2 size="18" />
              </div>
            )}

            <div className="mobile:hidden flex my-auto">
              <UserDropdown
                hideUserDropdown={hideUserDropdown}
                page={page}
                toggleUserSettings={toggleUserSettings}
              />
            </div>
            <Link
              className="desktop:hidden ml-2 my-auto"
              href={
                `/${page}` +
                (NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA &&
                currentChatSession
                  ? `?assistantId=${currentChatSession.persona_id}`
                  : "")
              }
            >
              <div className="cursor-pointer ml-2 mr-4 flex-none text-text-700 hover:text-text-600 transition-colors duration-300">
                <NewChatIcon size={20} />
              </div>
            </Link>
            <div
              style={{ transition: "width 0.30s ease-out" }}
              className={`
            hidden
            md:flex 
            mx-auto
            overflow-y-hidden 
            transition-all 
            duration-300 
            ease-in-out
            h-full
            ${documentSidebarToggled ? "w-[400px]" : "w-[0px]"}
            `}
            />
          </div>

          {page != "assistants" && (
            <div
              className={`
              h-20 absolute top-0 z-10 w-full sm:w-[90%] lg:w-[70%]
              bg-gradient-to-b via-50% z-[-1] from-background via-background to-background/10 flex
              transition-all duration-300 ease-in-out
              ${
                documentSidebarToggled
                  ? "left-[200px] transform -translate-x-[calc(50%+100px)]"
                  : "left-1/2 transform -translate-x-1/2"
              }
            `}
            />
          )}
        </div>
      </div>
    </div>
  );
}
