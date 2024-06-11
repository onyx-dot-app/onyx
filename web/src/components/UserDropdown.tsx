"use client";

import { useState, useRef, useContext } from "react";
import { FiSearch, FiMessageSquare, FiTool, FiLogOut } from "react-icons/fi";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { User } from "@/lib/types";
import { checkUserIsNoAuthUser, logout } from "@/lib/user";
import { BasicSelectable } from "@/components/BasicClickable";
import { Popover } from "./popover/Popover";
import { FaBrain } from "react-icons/fa";
import { LOGOUT_DISABLED } from "@/lib/constants";
import { Settings } from "@/app/admin/settings/interfaces";
import { SettingsContext } from "./settings/SettingsProvider";

export function UserDropdown({
  user,
  hideChatAndSearch,
}: {
  user: User | null;
  hideChatAndSearch?: boolean;
}) {
  const [userInfoVisible, setUserInfoVisible] = useState(false);
  const userInfoRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  const combinedSettings = useContext(SettingsContext);
  if (!combinedSettings) {
    return null;
  }
  const settings = combinedSettings.settings;

  const handleLogout = () => {
    logout().then((isSuccess) => {
      if (!isSuccess) {
        alert("Failed to logout");
      }
      router.push("/auth/login");
    });
  };

  const showAdminPanel = !user || user.role === "admin";
  const showLogout =
    user && !checkUserIsNoAuthUser(user.id) && !LOGOUT_DISABLED;

  return (
    <div className="relative" ref={userInfoRef}>
      <Popover
        open={userInfoVisible}
        onOpenChange={setUserInfoVisible}
        content={
          <BasicSelectable selected={false}>
            <div
              onClick={() => setUserInfoVisible(!userInfoVisible)}
              className="flex cursor-pointer"
            >
              <div className="my-auto bg-user rounded-lg px-2 text-base font-normal">
                {user && user.email ? user.email[0].toUpperCase() : "A"}
              </div>
            </div>
          </BasicSelectable>
        }
        popover={
          <div
            className={`
                text-strong 
                text-sm
                border 
                border-border 
                bg-background
                rounded-lg
                shadow-lg 
                flex 
                flex-col 
                w-full 
                max-h-96 
                overflow-y-auto 
                p-1
                overscroll-contain
              `}
          >
            {!hideChatAndSearch && (
              <>
                {settings.search_page_enabled && (
                  <Link
                    href="/search"
                    className="flex py-3 px-4 rounded cursor-pointer hover:bg-hover-light"
                  >
                    <FiSearch className="my-auto mr-2 text-lg" />
                    Danswer Search
                  </Link>
                )}
                {settings.chat_page_enabled && (
                  <>
                    <Link
                      href="/chat"
                      className="flex py-3 px-4 rounded cursor-pointer hover:bg-hover-light"
                    >
                      <FiMessageSquare className="my-auto mr-2 text-lg" />
                      Danswer Chat
                    </Link>
                    <Link
                      href="/assistants/mine"
                      className="flex py-3 px-4 rounded cursor-pointer hover:bg-hover-light"
                    >
                      <FaBrain className="my-auto mr-2 text-lg" />
                      My Assistants
                    </Link>
                  </>
                )}
              </>
            )}
            {showAdminPanel && (
              <>
                {!hideChatAndSearch && (
                  <div className="border-t border-border my-1" />
                )}
                <Link
                  href="/admin/indexing/status"
                  className="flex py-3 px-4 cursor-pointer rounded hover:bg-hover-light"
                >
                  <FiTool className="my-auto mr-2 text-lg" />
                  Admin Panel
                </Link>
              </>
            )}
            {showLogout && (
              <>
                {(!hideChatAndSearch || showAdminPanel) && (
                  <div className="border-t border-border my-1" />
                )}
                <div
                  onClick={handleLogout}
                  className="mt-1 flex py-3 px-4 cursor-pointer hover:bg-hover-light"
                >
                  <FiLogOut className="my-auto mr-2 text-lg" />
                  Log out
                </div>
              </>
            )}
          </div>
        }
        side="bottom"
        align="end"
        sideOffset={5}
        alignOffset={-10}
      />
    </div>
  );
}
