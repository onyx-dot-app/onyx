"use client";
import { User } from "@/lib/types";
import { UserDropdown } from "../UserDropdown";
import { FiShare2 } from "react-icons/fi";
import { SetStateAction, useContext, useEffect } from "react";
import { NewChatIcon } from "../icons/icons";
import { NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA } from "@/lib/constants";
import { ChatSession } from "@/app/chat/interfaces";
import Link from "next/link";
import { pageType } from "@/app/chat/sessionSidebar/types";
import { useRouter } from "next/navigation";
import { ChatBanner } from "@/app/chat/ChatBanner";
import LogoType from "../header/LogoType";
import { useUser } from "../user/UserProvider";

export default function FunctionalHeader({
  page,
  currentChatSession,
  setSharingModalVisible,
  toggleSidebar = () => null,
  reset = () => null,
  sidebarToggled,
}: {
  reset?: () => void;
  page: pageType;
  sidebarToggled?: boolean;
  currentChatSession?: ChatSession | null | undefined;
  setSharingModalVisible?: (value: SetStateAction<boolean>) => void;
  toggleSidebar?: () => void;
}) {
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
    // <div className="pb-6 left-0 sticky top-0 z-20 w-full relative flex">

    <div className="left-0 bg-transparent sticky top-0 z-20 w-full relative flex">
      <div className="mt-2 mx-2.5 cursor-pointer text-text-700 relative flex w-full">
        <LogoType
          assistantId={currentChatSession?.persona_id}
          page={page}
          toggleSidebar={toggleSidebar}
          handleNewChat={handleNewChat}
        />
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
          <LogoType
            page={page}
            toggleSidebar={toggleSidebar}
            handleNewChat={handleNewChat}
          />
        </div>

        <div className="absolute right-0 top-0 flex gap-x-2">
          {setSharingModalVisible && (
            <div
              onClick={() => setSharingModalVisible(true)}
              className="mobile:hidden my-auto rounded cursor-pointer hover:bg-hover-light"
            >
              <FiShare2 size="18" />
            </div>
          )}

          <div className="mobile:hidden flex my-auto">
            <UserDropdown />
          </div>
          <Link
            className="desktop:hidden my-auto"
            href={
              `/${page}` +
              (NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA &&
              currentChatSession
                ? `?assistantId=${currentChatSession.persona_id}`
                : "")
            }
          >
            <div className="cursor-pointer mr-4 flex-none text-text-700 hover:text-text-600 transition-colors duration-300">
              <NewChatIcon size={20} />
            </div>
          </Link>
        </div>
      </div>

      {page != "assistants" && (
        <div className="h-20 left-0 absolute top-0 z-10 w-full bg-gradient-to-b via-50% z-[-1] from-background via-background to-background/10 flex" />
      )}
    </div>
  );
}
