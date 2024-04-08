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

interface ChatSidebarProps {
  existingChats: ChatSession[];
  currentChatSession: ChatSession | null | undefined;
  user: User | null;
}

export const ChatSidebar = ({
  existingChats,
  currentChatSession,
  user,
}: ChatSidebarProps) => {
  const router = useRouter();

  const groupedChatSessions = groupSessionsByDateRange(existingChats);

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
        w-64
        2xl:w-72
        ${HEADER_PADDING}
        border-r 
        border-border 
        flex 
        flex-col 
        h-screen
        transition-transform`}
      id="chat-sidebar"
    >
      <Link
        href={
          "/chat" +
          (NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA && currentChatSession
            ? `?personaId=${currentChatSession.persona_id}`
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

      <div className="mt-1 pb-1 mb-1 ml-3 overflow-y-auto h-full">
        {Object.entries(groupedChatSessions).map(
          ([dateRange, chatSessions]) => {
            if (chatSessions.length > 0) {
              return (
                <div key={dateRange}>
                  <div className="text-xs text-subtle flex pb-0.5 mb-1.5 mt-5 font-bold">
                    {dateRange}
                  </div>
                  {chatSessions.map((chat) => {
                    const isSelected = currentChatId === chat.id;
                    return (
                      <div key={`${chat.id}-${chat.name}`} className="mr-3">
                        <ChatSessionDisplay
                          chatSession={chat}
                          isSelected={isSelected}
                        />
                      </div>
                    );
                  })}
                </div>
              );
            }
          }
        )}
      </div>

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
