"use client";

import { useState, useRef, useContext, useEffect, useMemo } from "react";
import { FiLogOut } from "react-icons/fi";
import Link from "next/link";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { UserRole } from "@/lib/types";
import { checkUserIsNoAuthUser, logout } from "@/lib/user";
import { Popover } from "./popover/Popover";
import { LOGOUT_DISABLED } from "@/lib/constants";
import { SettingsContext } from "./settings/SettingsProvider";
import { BellIcon, LightSettingsIcon, UserIcon } from "./icons/icons";
import { pageType } from "@/app/chat/sessionSidebar/types";
import { NavigationItem, Notification } from "@/app/admin/settings/interfaces";
import DynamicFaIcon, { preloadIcons } from "./icons/DynamicFaIcon";
import { useUser } from "./user/UserProvider";
import { usePaidEnterpriseFeaturesEnabled } from "./settings/usePaidEnterpriseFeaturesEnabled";
import { Notifications } from "./chat/Notifications";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface DropdownOptionProps {
  href?: string;
  onClick?: () => void;
  icon: React.ReactNode;
  label: string;
  openInNewTab?: boolean;
}

const DropdownOption: React.FC<DropdownOptionProps> = ({
  href,
  onClick,
  icon,
  label,
  openInNewTab,
}) => {
  const content = (
    <div className="flex py-1.5 text-sm px-2 gap-x-2 text-black text-sm cursor-pointer rounded hover:bg-background-300">
      {icon}
      {label}
    </div>
  );

  if (href) {
    return (
      <Link
        href={href}
        target={openInNewTab ? "_blank" : undefined}
        rel={openInNewTab ? "noopener noreferrer" : undefined}
      >
        {content}
      </Link>
    );
  } else {
    return <div onClick={onClick}>{content}</div>;
  }
};

export function UserDropdown({
  page,
  toggleUserSettings,
  hideUserDropdown,
}: {
  page?: pageType;
  toggleUserSettings?: () => void;
  hideUserDropdown?: boolean;
}) {
  const { user, isCurator } = useUser();
  const [userInfoVisible, setUserInfoVisible] = useState(false);
  const userInfoRef = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [showNotifications, setShowNotifications] = useState(false);

  const combinedSettings = useContext(SettingsContext);
  const customNavItems: NavigationItem[] = useMemo(
    () => combinedSettings?.enterpriseSettings?.custom_nav_items || [],
    [combinedSettings]
  );
  const {
    data: notifications,
    error,
    mutate: refreshNotifications,
  } = useSWR<Notification[]>("/api/notifications", errorHandlingFetcher);

  useEffect(() => {
    const iconNames = customNavItems
      .map((item) => item.icon)
      .filter((icon) => icon) as string[];
    preloadIcons(iconNames);
  }, [customNavItems]);

  if (!combinedSettings) {
    return null;
  }

  const handleLogout = () => {
    logout().then((isSuccess) => {
      if (!isSuccess) {
        alert("Failed to logout");
        return;
      }

      // Construct the current URL
      const currentUrl = `${pathname}${
        searchParams.toString() ? `?${searchParams.toString()}` : ""
      }`;

      // Encode the current URL to use as a redirect parameter
      const encodedRedirect = encodeURIComponent(currentUrl);

      // Redirect to login page with the current page as a redirect parameter
      router.push(`/auth/login?next=${encodedRedirect}`);
    });
  };

  const showAdminPanel = !user || user.role === UserRole.ADMIN;

  const showCuratorPanel = user && isCurator;
  const showLogout =
    user && !checkUserIsNoAuthUser(user.id) && !LOGOUT_DISABLED;

  const onOpenChange = (open: boolean) => {
    setUserInfoVisible(open);
    setShowNotifications(false);
  };

  return (
    <div className="group relative" ref={userInfoRef}>
      <Popover
        open={userInfoVisible}
        onOpenChange={onOpenChange}
        content={
          <div
            id="onyx-user-dropdown"
            onClick={() => setUserInfoVisible(!userInfoVisible)}
            className="flex relative cursor-pointer"
          >
            <div
              className="
                my-auto
                bg-background-900
                ring-2
                ring-transparent
                group-hover:ring-background-300/50
                transition-ring
                duration-150
                rounded-full
                inline-block
                flex-none
                w-6
                h-6
                flex
                items-center
                justify-center
                text-white
                text-base
              "
            >
              {user && user.email ? user.email[0].toUpperCase() : "A"}
            </div>
            {notifications && notifications.length > 0 && (
              <div className="absolute -right-0.5 -top-0.5 w-3 h-3 bg-red-500 rounded-full"></div>
            )}
          </div>
        }
        popover={
          <div
            className={`
                p-2
                ${page != "admin" && showNotifications ? "w-72" : "w-[175px]"}
                text-strong 
                text-sm
                border 
                border-border 
                bg-background
                dark:bg-[#2F2F2F]
                rounded-lg
                shadow-lg 
                flex 
                flex-col 
                max-h-96 
                overflow-y-auto 
                p-1
                overscroll-contain
              `}
          >
            {page != "admin" && showNotifications ? (
              <Notifications
                navigateToDropdown={() => setShowNotifications(false)}
                notifications={notifications || []}
                refreshNotifications={refreshNotifications}
              />
            ) : hideUserDropdown ? (
              <DropdownOption
                onClick={() => router.push("/auth/login")}
                icon={<UserIcon className="h-5w-5 my-auto " />}
                label="Log In"
              />
            ) : (
              <>
                {customNavItems.map((item, i) => (
                  <DropdownOption
                    key={i}
                    href={item.link}
                    icon={
                      item.svg_logo ? (
                        <div
                          className="
                        h-4
                        w-4
                        my-auto
                        overflow-hidden
                        flex
                        items-center
                        justify-center
                      "
                          aria-label={item.title}
                        >
                          <svg
                            viewBox="0 0 24 24"
                            width="100%"
                            height="100%"
                            preserveAspectRatio="xMidYMid meet"
                            dangerouslySetInnerHTML={{ __html: item.svg_logo }}
                          />
                        </div>
                      ) : (
                        <DynamicFaIcon
                          name={item.icon!}
                          className="h-4 w-4 my-auto "
                        />
                      )
                    }
                    label={item.title}
                    openInNewTab
                  />
                ))}

                {showAdminPanel ? (
                  <DropdownOption
                    href="/admin/indexing/status"
                    icon={<LightSettingsIcon size={16} className="my-auto" />}
                    label="Admin Panel"
                  />
                ) : (
                  showCuratorPanel && (
                    <DropdownOption
                      href="/admin/indexing/status"
                      icon={<LightSettingsIcon size={16} className="my-auto" />}
                      label="Curator Panel"
                    />
                  )
                )}

                {toggleUserSettings && (
                  <DropdownOption
                    onClick={toggleUserSettings}
                    icon={<UserIcon size={16} className="my-auto" />}
                    label="User Settings"
                  />
                )}

                <DropdownOption
                  onClick={() => {
                    setUserInfoVisible(true);
                    setShowNotifications(true);
                  }}
                  icon={<BellIcon size={16} className="my-auto" />}
                  label={`Notifications ${
                    notifications && notifications.length > 0
                      ? `(${notifications.length})`
                      : ""
                  }`}
                />

                {showLogout &&
                  (showCuratorPanel ||
                    showAdminPanel ||
                    customNavItems.length > 0) && (
                    <div className="border-t border-border my-1" />
                  )}

                {showLogout && (
                  <DropdownOption
                    onClick={handleLogout}
                    icon={<FiLogOut size={16} className="my-auto" />}
                    label="Log out"
                  />
                )}
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
