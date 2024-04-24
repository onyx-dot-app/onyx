"use client";

import {
  FiLogOut,
  FiMessageSquare,
  FiMoreHorizontal,
  FiPlusSquare,
  FiSearch,
  FiTool,
} from "react-icons/fi";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { User } from "@/lib/types";
import { logout } from "@/lib/user";
import { BasicClickable, BasicSelectable } from "@/components/BasicClickable";
import { ChatSessionDisplay } from "./SessionDisplay";
import { ChatSession } from "../interfaces";
import { groupSessionsByDateRange } from "../lib";
import {
  HEADER_PADDING,
  NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA,
} from "@/lib/constants";
import { ChatTab } from "./ChatTab";
import { AssistantsTab } from "./AssistantsTab";
import { Persona } from "@/app/admin/assistants/interfaces";
import Cookies from "js-cookie";
import { SIDEBAR_TAB_COOKIE, Tabs } from "./constants";

export const ChatSidebar = ({
  existingChats,
  currentChatSession,
  personas,
  onPersonaChange,
  user,
  defaultTab,
}: {
  existingChats: ChatSession[];
  currentChatSession: ChatSession | null | undefined;
  personas: Persona[];
  onPersonaChange: (persona: Persona | null) => void;
  user: User | null;
  defaultTab?: Tabs;
}) => {
  const router = useRouter();

  const [openTab, _setOpenTab] = useState(defaultTab || Tabs.CHATS);
  const setOpenTab = (tab: Tabs) => {
    Cookies.set(SIDEBAR_TAB_COOKIE, tab);
    _setOpenTab(tab);
  };

  function TabOption({ tab }: { tab: Tabs }) {
    return (
      <div
        className={
          "font-bold p-1 rounded-lg hover:bg-hover cursor-pointer " +
          (openTab === tab ? "bg-hover" : "")
        }
        onClick={() => {
          setOpenTab(tab);
        }}
      >
        {tab}
      </div>
    );
  }

  const [userInfoVisible, setUserInfoVisible] = useState(false);
  const userInfoRef = useRef<HTMLDivElement>(null);

  const handleLogout = () => {
    logout().then((isSuccess) => {
      if (!isSuccess) {
        alert("Failed to logout");
      }
      router.push("/auth/login");
    });
  };

  // hides logout popup on any click outside
  const handleClickOutside = (event: MouseEvent) => {
    if (
      userInfoRef.current &&
      !userInfoRef.current.contains(event.target as Node)
    ) {
      setUserInfoVisible(false);
    }
  };

  useEffect(() => {
    document.addEventListener("mousedown", handleClickOutside);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const currentChatId = currentChatSession?.id;

  // prevent the NextJS Router cache from causing the chat sidebar to not
  // update / show an outdated list of chats
  useEffect(() => {
    router.refresh();
  }, [currentChatId]);

  return (
    <div
      className={`
        flex-none
        w-64
        3xl:w-72
        ${HEADER_PADDING}
        border-r 
        border-border 
        flex 
        flex-col 
        h-screen
        transition-transform`}
      id="chat-sidebar"
    >
      <div className="flex w-full mx-4 mt-4 text-sm gap-x-4 pb-2 border-b border-border">
        <TabOption tab={Tabs.CHATS} />
        <TabOption tab={Tabs.ASSISTANTS} />
      </div>

      {openTab == Tabs.CHATS && (
        <>
          <Link
            href={
              "/chat" +
              (NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA &&
              currentChatSession
                ? `?assistantId=${currentChatSession.persona_id}`
                : "")
            }
            className="mx-3 mt-5"
          >
            <BasicClickable fullWidth>
              <div className="flex text-sm">
                <FiPlusSquare className="my-auto mr-2" /> New Chat
              </div>
            </BasicClickable>
          </Link>
          <ChatTab
            existingChats={existingChats}
            currentChatId={currentChatId}
          />
        </>
      )}

      {openTab == Tabs.ASSISTANTS && (
        <>
          <Link href="/assistants/new" className="mx-3 mt-5">
            <BasicClickable fullWidth>
              <div className="flex text-sm">
                <FiPlusSquare className="my-auto mr-2" /> New Assistant
              </div>
            </BasicClickable>
          </Link>
          <AssistantsTab
            personas={personas}
            onPersonaChange={onPersonaChange}
            user={user}
          />
        </>
      )}

      <div
        className="mt-auto py-2 border-t border-border px-3"
        ref={userInfoRef}
      >
        <div className="relative text-strong">
          {userInfoVisible && (
            <div
              className={
                (user ? "translate-y-[-110%]" : "translate-y-[-115%]") +
                " absolute top-0 bg-background border border-border z-30 w-full rounded text-strong text-sm"
              }
            >
              <Link
                href="/search"
                className="flex py-3 px-4 cursor-pointer hover:bg-hover"
              >
                <FiSearch className="my-auto mr-2" />
                Danswer Search
              </Link>
              <Link
                href="/chat"
                className="flex py-3 px-4 cursor-pointer hover:bg-hover"
              >
                <FiMessageSquare className="my-auto mr-2" />
                Danswer Chat
              </Link>
              {(!user || user.role === "admin") && (
                <Link
                  href="/admin/indexing/status"
                  className="flex py-3 px-4 cursor-pointer border-t border-border hover:bg-hover"
                >
                  <FiTool className="my-auto mr-2" />
                  Admin Panel
                </Link>
              )}
              {user && (
                <div
                  onClick={handleLogout}
                  className="flex py-3 px-4 cursor-pointer border-t border-border rounded hover:bg-hover"
                >
                  <FiLogOut className="my-auto mr-2" />
                  Log out
                </div>
              )}
            </div>
          )}
          <BasicSelectable fullWidth selected={false}>
            <div
              onClick={() => setUserInfoVisible(!userInfoVisible)}
              className="flex h-8"
            >
              <div className="my-auto mr-2 bg-user rounded-lg px-1.5">
                {user && user.email ? user.email[0].toUpperCase() : "A"}
              </div>
              <p className="my-auto">
                {user ? user.email : "Anonymous Possum"}
              </p>
              <FiMoreHorizontal className="my-auto ml-auto mr-2" size={20} />
            </div>
          </BasicSelectable>
        </div>
      </div>
    </div>
  );
};
