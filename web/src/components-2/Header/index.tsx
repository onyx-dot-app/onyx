"use client";

import React, { useState, useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { UserDropdown } from "@/components/UserDropdown";
import { UserSettingsModal } from "@/app/chat/modal/UserSettingsModal";
import { useChatContext } from "@/components/context/ChatContext";
import { useUser } from "@/components/user/UserProvider";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useFederatedOAuthStatus } from "@/lib/hooks/useFederatedOAuthStatus";
import { useLlmManager } from "@/lib/hooks";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { useSidebar } from "@/components/context/SidebarProvider";
import {
  MagnifyingIcon,
  ChatIcon,
  ChevronDownIcon,
} from "@/components/icons/icons";

const dropdownItems = [
  {
    title: "Search",
    description: "Quick Search for Documents",
    icon: MagnifyingIcon,
    link: "/search",
  },
  {
    title: "Chat",
    description: "Conversation and Research with Follow-Up Questions",
    icon: ChatIcon,
    link: "/chat",
  },
];

interface DropdownItemProps {
  title: string;
  description: string;
  onClick: () => void;
  icon?: React.ComponentType<{ size?: number; className?: string }>;
}

function DropdownItem({
  title,
  description,
  onClick,
  icon: Icon,
}: DropdownItemProps) {
  return (
    <DropdownMenuItem onClick={onClick} className="px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="flex items-center flex-1 flex-col h-full">
          {Icon && <Icon size={18} />}
        </div>
        <div className="flex flex-col">
          <span className="text-md">{title}</span>
          <span className="text-xs text-subtle">{description}</span>
        </div>
      </div>
    </DropdownMenuItem>
  );
}

export function Header() {
  const [userSettingsOpen, setUserSettingsOpen] = useState(false);
  const [selectedMode, setSelectedMode] = useState<string>("");
  const { sidebarVisible } = useSidebar();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (pathname.startsWith("/chat")) {
      setSelectedMode("Chat");
    } else if (pathname.startsWith("/search")) {
      setSelectedMode("Search");
    } else {
      throw new Error(
        `Invalid URL prefix: ${pathname}. Expected /chat or /search`
      );
    }
  }, [pathname]);
  const { llmProviders, ccPairs } = useChatContext();
  const { user } = useUser();
  const { popup, setPopup } = usePopup();
  const {
    connectors: federatedConnectors,
    refetch: refetchFederatedConnectors,
  } = useFederatedOAuthStatus();

  const llmManager = useLlmManager(llmProviders, undefined, undefined);

  const toggleUserSettings = () => {
    setUserSettingsOpen(!userSettingsOpen);
  };

  const handleModeSelection = (mode: string) => {
    setSelectedMode(mode);
    const selectedItem = dropdownItems.find((item) => item.title === mode);
    if (selectedItem?.link) {
      router.push(selectedItem.link);
    }
  };

  const selectedItem = dropdownItems.find(
    (item) => item.title === selectedMode
  );

  console.log(sidebarVisible);

  return (
    <>
      <div className="flex w-full items-center justify-start gap-2 z-50 px-4 py-2">
        <div
          className={`flex flex-1 transition-transform duration-300 ease-in-out ${sidebarVisible ? "translate-x-0" : "translate-x-[130px]"}`}
        >
          <DropdownMenu>
            <DropdownMenuTrigger className="flex items-center gap-2 px-3 py-2 rounded-md hover:bg-accent-background-hovered transition-colors duration-200 ease-in-out">
              {selectedItem?.icon && <selectedItem.icon size={16} />}
              <span className="font-medium">{selectedMode}</span>
              <ChevronDownIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {dropdownItems.map((item) => (
                <DropdownItem
                  key={item.title}
                  title={item.title}
                  description={item.description}
                  icon={item.icon}
                  onClick={() => handleModeSelection(item.title)}
                />
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div className="flex">
          <UserDropdown
            hideUserDropdown={false}
            toggleUserSettings={toggleUserSettings}
          />
        </div>
      </div>
      {userSettingsOpen && (
        <UserSettingsModal
          setPopup={setPopup}
          setCurrentLlm={(newLlm) => llmManager.updateCurrentLlm(newLlm)}
          defaultModel={user?.preferences.default_model!}
          llmProviders={llmProviders}
          ccPairs={ccPairs}
          federatedConnectors={federatedConnectors}
          refetchFederatedConnectors={refetchFederatedConnectors}
          onClose={() => setUserSettingsOpen(false)}
        />
      )}
      {popup}
    </>
  );
}
