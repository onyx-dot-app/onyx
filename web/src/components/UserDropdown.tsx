"use client";

import { useState, useRef, useContext, useEffect } from "react";
import { FiLogOut } from "react-icons/fi";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { User, UserRole } from "@/lib/types";
import { checkUserIsNoAuthUser, logout } from "@/lib/user";
import { Popover } from "./popover/Popover";
import { LOGOUT_DISABLED } from "@/lib/constants";
import { SettingsContext } from "./settings/SettingsProvider";
import {
  AssistantsIconSkeleton,
  LightSettingsIcon,
  UsersIcon,
  FileIcon
} from "./icons/icons";
import { pageType } from "@/app/chat/sessionSidebar/types";
import { NavigationItem } from "@/app/admin/settings/interfaces";
import DynamicFaIcon, { preloadIcons } from "./icons/DynamicFaIcon";

interface DropdownOptionProps {
  href?: string;
  onClick?: () => void;
  icon: React.ReactNode;
  label: string;
}

const DropdownOption: React.FC<DropdownOptionProps> = ({
  href,
  onClick,
  icon,
  label,
}) => {
  const content = (
    <div className="flex py-3 px-4 cursor-pointer rounded hover:bg-hover-light">
      {icon}
      {label}
    </div>
  );

  return href ? (
    <Link href={href}>{content}</Link>
  ) : (
    <div onClick={onClick}>{content}</div>
  );
};

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
  const customNavItems: NavigationItem[] =
    combinedSettings?.enterpriseSettings?.custom_nav_items || [];

  useEffect(() => {
    const iconNames = customNavItems.map((item) => item.icon);
    preloadIcons(iconNames);
  }, [customNavItems]);

  if (!combinedSettings) {
    return null;
  }

  const handleLogout = () => {
    logout().then((isSuccess) => {
      if (!isSuccess) {
        alert("Failed to logout");
      }
      router.push("/auth/login");
    });
  };

  const showAdminPanel = !user || user.role === UserRole.ADMIN;
  const showCuratorPanel =
    user &&
    (user.role === UserRole.CURATOR || user.role === UserRole.GLOBAL_CURATOR);
  const showLogout =
    user && !checkUserIsNoAuthUser(user.id) && !LOGOUT_DISABLED;
  const showPrivacy = true;
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
            {customNavItems.map((item, i) => (
              <DropdownOption
                key={i}
                href={item.link}
                icon={
                  <DynamicFaIcon
                    name={item.icon}
                    className="h-4 w-4 my-auto mr-2"
                  />
                }
                label={item.title}
              />
            ))}

            {showAdminPanel ? (
              <DropdownOption
                href="/admin/indexing/status"
                icon={<LightSettingsIcon className="h-5 w-5 my-auto mr-2" />}
                label="Admin Panel"
              />
            ) : (
              showCuratorPanel && (
                <DropdownOption
                  href="/admin/indexing/status"
                  icon={<LightSettingsIcon className="h-5 w-5 my-auto mr-2" />}
                  label="Curator Panel"
                />
              )
            )}
            {showPrivacy && (
              <>
                <Link
                  href="/pages/privacy"
                  className="flex py-3 px-4 cursor-pointer !
                   rounded hover:bg-hover-light"
                >
                  <FileIcon className="h-5 w-5 my-auto mr-2" />
                  Privacy Architecture
                </Link>
              </>
            )}
            {showLogout &&
              (showCuratorPanel ||
                showAdminPanel ||
                customNavItems.length > 0) && (
                <div className="border-t border-border my-1" />
              )}
            {showLogout && (
              <DropdownOption
                onClick={handleLogout}
                icon={<FiLogOut className="my-auto mr-2 text-lg" />}
                label="Log out"
              />
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
