"use client";

import { useState, useRef, useContext, useEffect, useMemo } from "react";
import { FiLogOut } from "react-icons/fi";
import Link from "next/link";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { UserRole } from "@/lib/types";
import { checkUserIsNoAuthUser, logout } from "@/lib/user";
import { Popover } from "@/components/popover/Popover";
import { LOGOUT_DISABLED } from "@/lib/constants";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import {
  BellIcon,
  LightSettingsIcon,
  UserIcon,
} from "@/components/icons/icons";
import { pageType } from "@/components/sidebar/types";
import { NavigationItem, Notification } from "@/app/admin/settings/interfaces";
import DynamicFaIcon, { preloadIcons } from "@/components/icons/DynamicFaIcon";
import { useUser } from "@/components/user/UserProvider";
import { Notifications } from "@/components/chat/Notifications";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Text from "@/components-2/Text";

interface DropdownOptionProps {
  href?: string;
  onClick?: () => void;
  icon: React.ReactNode;
  label: string;
  openInNewTab?: boolean;
}

function DropdownOption({
  href,
  onClick,
  icon,
  label,
  openInNewTab,
}: DropdownOptionProps) {
  const content = (
    <div className="flex py-1.5 text-sm px-2 gap-x-2 text-sm cursor-pointer rounded hover:bg-background-tint-03">
      {icon}
      <Text>{label}</Text>
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
}

interface UserDropdownProps {
  page?: pageType;
  toggleUserSettings?: () => void;
  hideUserDropdown?: boolean;
}

export function UserDropdown({
  page,
  toggleUserSettings,
  hideUserDropdown,
}: UserDropdownProps) {
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

  function handleLogout() {
    logout().then((isSuccess) => {
      if (!isSuccess) {
        alert("Failed to logout");
        return;
      }

      // Construct the current URL
      const currentUrl = `${pathname}${
        searchParams?.toString() ? `?${searchParams.toString()}` : ""
      }`;

      // Encode the current URL to use as a redirect parameter
      const encodedRedirect = encodeURIComponent(currentUrl);

      // Redirect to login page with the current page as a redirect parameter
      router.push(`/auth/login?next=${encodedRedirect}`);
    });
  }

  const showAdminPanel = !user || user.role === UserRole.ADMIN;

  const showCuratorPanel = user && isCurator;
  const showLogout =
    user && !checkUserIsNoAuthUser(user.id) && !LOGOUT_DISABLED;

  function onOpenChange(open: boolean) {
    setUserInfoVisible(open);
    setShowNotifications(false);
  }

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
            <button
              className="
                my-auto
                bg-background-tint-inverted-02
                ring-2
                ring-transparent
                group-hover:ring-background-tint-03/50
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
                text-text-inverted-01
                text-base
              "
            >
              <Text inverted>
                {user && user.email
                  ? user.email[0] !== undefined && user.email[0].toUpperCase()
                  : "A"}
              </Text>
            </button>
            {notifications && notifications.length > 0 && (
              <div className="absolute -right-0.5 -top-0.5 w-3 h-3 bg-status-error-05 rounded-full" />
            )}
          </div>
        }
        popover={
          <div
            className={`
                p-2
                ${page != "admin" && showNotifications ? "w-72" : "w-[175px]"}
                text-text-01
                text-sm
                border
                bg-background-tint-01
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
                icon={<UserIcon className="h-5 w-5 my-auto text-text-05" />}
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
                          className="h-4 w-4 my-auto text-text-05"
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
                    icon={
                      <LightSettingsIcon
                        size={16}
                        className="my-auto text-text-05"
                      />
                    }
                    label="Admin Panel"
                  />
                ) : (
                  showCuratorPanel && (
                    <DropdownOption
                      href="/admin/indexing/status"
                      icon={
                        <LightSettingsIcon
                          size={16}
                          className="my-auto text-text-05"
                        />
                      }
                      label="Curator Panel"
                    />
                  )
                )}

                {toggleUserSettings && (
                  <DropdownOption
                    onClick={toggleUserSettings}
                    icon={
                      <UserIcon size={16} className="my-auto text-text-05" />
                    }
                    label="User Settings"
                  />
                )}

                <DropdownOption
                  onClick={() => {
                    setUserInfoVisible(true);
                    setShowNotifications(true);
                  }}
                  icon={<BellIcon size={16} className="my-auto text-text-05" />}
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
                    <div className="border-t my-1" />
                  )}

                {showLogout && (
                  <DropdownOption
                    onClick={handleLogout}
                    icon={
                      <FiLogOut size={16} className="my-auto text-text-05" />
                    }
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
