"use client";

import React, { ReactNode, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ChatIcon, SearchIcon } from "@/components/icons/icons";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import KeyboardSymbol from "@/lib/browserUtilities";

const ToggleSwitch = () => {
  const commandSymbol = KeyboardSymbol();
  const pathname = usePathname();
  const router = useRouter();

  const [activeTab, setActiveTab] = useState(() => {
    return pathname == "/search" ? "search" : "chat";
  });

  const [isInitialLoad, setIsInitialLoad] = useState(true);

  useEffect(() => {
    const newTab = pathname === "/search" ? "search" : "chat";
    setActiveTab(newTab);
    localStorage.setItem("activeTab", newTab);
    setIsInitialLoad(false);
  }, [pathname]);

  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    localStorage.setItem("activeTab", tab);
    router.push(tab === "search" ? "/search" : "/chat");
  };

  return (
    <div className="bg-gray-100 flex rounded-full p-1">
      <div
        className={`absolute top-1 bottom-1  ${
          activeTab === "chat" ? "w-[45%]" : "w-[50%]"
        } bg-white rounded-full shadow ${
          isInitialLoad ? "" : "transition-transform duration-300 ease-in-out"
        } ${activeTab === "chat" ? "translate-x-[115%]" : "translate-x-[1%]"}`}
      />
      <button
        className={`px-4 py-2 rounded-full text-sm font-medium transition-colors duration-300 ease-in-out flex items-center relative z-10 ${
          activeTab === "search"
            ? "text-gray-800"
            : "text-gray-500 hover:text-gray-700"
        }`}
        onClick={() => handleTabChange("search")}
      >
        <SearchIcon size={16} className="mr-2" />
        <p className="items-baseline flex">
          Search
          <span className="text-xs ml-2">{commandSymbol}S</span>
        </p>
      </button>
      <button
        className={`px-4 py-2 rounded-full text-sm font-medium transition-colors duration-300 ease-in-out flex  items-center relative z-10 ${
          activeTab === "chat"
            ? "text-gray-800"
            : "text-gray-500 hover:text-gray-700"
        }`}
        onClick={() => handleTabChange("chat")}
      >
        <ChatIcon size={16} className="mr-2" />
        <p className="items-baseline flex">
          Chat
          <span className="text-xs ml-2">{commandSymbol}D</span>
        </p>
      </button>
    </div>
  );
};

export default function FunctionalWrapper({
  // children,
  initiallyToggled,
  content,
}: {
  // children: React.ReactNode;
  content: (toggledSidebar: boolean, toggle: () => void) => ReactNode;
  initiallyToggled: boolean;
}) {
  const router = useRouter();

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey) {
        const newPage = event.shiftKey;
        switch (event.key.toLowerCase()) {
          case "d":
            event.preventDefault();
            if (newPage) {
              window.open("/chat", "_blank");
            } else {
              router.push("/chat");
            }
            break;
          case "s":
            event.preventDefault();
            if (newPage) {
              window.open("/search", "_blank");
            } else {
              router.push("/search");
            }
            break;
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [router]);
  const settings = useContext(SettingsContext)?.settings;

  const [toggledSidebar, setToggledSidebar] = useState(initiallyToggled);

  const toggle = () => {
    setToggledSidebar((toggledSidebar) => !toggledSidebar);
  };

  return (
    <>
      {(!settings ||
        (settings.search_page_enabled && settings.chat_page_enabled)) && (
        <div className="z-[40] flex fixed top-4 left-1/2 transform -translate-x-1/2">
          <div
            style={{ transition: "width 0.30s ease-out" }}
            className={`flex-none overflow-y-hidden bg-background-100 transition-all bg-opacity-80duration-300 ease-in-out h-full
                        ${toggledSidebar ? "w-[300px] " : "w-[0px]"}`}
          />
          <div className="relative">
            <ToggleSwitch />
          </div>
        </div>
      )}

      <div className="absolute left-0 top-0 w-full h-full">
        {content(toggledSidebar, toggle)}
      </div>
    </>
  );
}
