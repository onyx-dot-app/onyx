"use client";

import { useState, useRef, useContext } from "react";
import { FiLogOut } from "react-icons/fi";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { User } from "@/lib/types";
import { checkUserIsNoAuthUser, logout } from "@/lib/user";
import { Popover } from "./popover/Popover";
import { LOGOUT_DISABLED } from "@/lib/constants";
import { SettingsContext } from "./settings/SettingsProvider";
import { LightSettingsIcon } from "./icons/icons";
import { pageType } from "@/app/chat/sessionSidebar/types";

export function UserDropdown({
  user,
  page,
}: {
  user: User | null;
  page?: pageType;
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
    <div className="group relative" ref={userInfoRef}>
      <Popover
        open={userInfoVisible}
        onOpenChange={setUserInfoVisible}
        content={
          <div
            onClick={() => setUserInfoVisible(!userInfoVisible)}
            className="flex cursor-pointer"
          >
            <div
              className="
                my-auto
                bg-background-strong
                ring-2
                ring-transparent
                group-hover:ring-background-300/50
                transition-ring
                duration-150
                rounded-lg
                inline-block
                flex-none
                px-2
                text-base
              "
            >
              {user && user.email ? user.email[0].toUpperCase() : "A"}
            </div>
          </div>
        }
        popover={
          <div
            className={`
                p-2
                min-w-[200px]
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
            {showAdminPanel && (
              <>
                <Link
                  href="/admin/indexing/status"
                  className="flex py-3 px-4 cursor-pointer !
                   rounded hover:bg-hover-light"
                >
                  <LightSettingsIcon className="h-5 w-5 my-auto mr-2" />
                  Admin Panel
                </Link>
              </>
            )}
            {showLogout && (
              <>
                {(!(page == "search" || page == "chat") || showAdminPanel) && (
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
