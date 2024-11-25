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
  const settings = useContext(SettingsContext);

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
    if (settings?.isMobile && window) {
      window.location.href = tab;
    } else {
      router.push(tab === "search" ? "/search" : "/chat");
    }
  };

  return (
    <div className="bg-background-toggle mobile:mt-8 flex rounded-full p-1">
      <div
        className={`absolute mobile:mt-8 top-1 bottom-1 ${
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
        <div className="flex  items-center">
          Search
          <div className="ml-2 flex content-center">
            <span className="leading-none pb-[1px] my-auto">
              {commandSymbol}
            </span>
            <span className="my-auto">S</span>
          </div>
        </div>
      </button>
      <button
        className={`px-4 py-2 rounded-full text-sm font-medium transition-colors duration-300 ease-in-out flex items-center relative z-10 ${
          activeTab === "chat"
            ? "text-gray-800"
            : "text-gray-500 hover:text-gray-700"
        }`}
        onClick={() => handleTabChange("chat")}
      >
        <ChatIcon size={16} className="mr-2" />
        <div className="items-end flex">
          Chat
          <div className="ml-2 flex content-center">
            <span className="leading-none pb-[1px] my-auto">
              {commandSymbol}
            </span>
            <span className="my-auto">D</span>
          </div>
        </div>
      </button>
    </div>
  );
};

export default function FunctionalWrapper({
  initiallyToggled,
  content,
}: {
  content: (
    toggledSidebar: boolean,
    toggle: (toggled?: boolean) => void
  ) => ReactNode;
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
  const combinedSettings = useContext(SettingsContext);
  const settings = combinedSettings?.settings;
  const chatBannerPresent =
    combinedSettings?.enterpriseSettings?.custom_header_content;
  const twoLines =
    combinedSettings?.enterpriseSettings?.two_lines_for_chat_header;

  const [toggledSidebar, setToggledSidebar] = useState(initiallyToggled);

  const toggle = (value?: boolean) => {
    setToggledSidebar((toggledSidebar) =>
      value !== undefined ? value : !toggledSidebar
    );
  };

  return (
    <>
      {(!settings ||
        (settings.search_page_enabled && settings.chat_page_enabled)) && (
        <div
          className={`mobile:hidden z-30 flex fixed ${
            chatBannerPresent ? (twoLines ? "top-20" : "top-14") : "top-4"
          } left-1/2 transform -translate-x-1/2`}
        >
          <div
            style={{ transition: "width 0.30s ease-out" }}
            className={`flex-none overflow-y-hidden bg-background-100 transition-all bg-opacity-80 duration-300 ease-in-out h-full
                        ${toggledSidebar ? "w-[250px] " : "w-[0px]"}`}
          />
          <div className="relative">
            <ToggleSwitch />
          </div>
        </div>
      )}

      <div className="overscroll-y-contain overflow-y-scroll overscroll-contain left-0 top-0 w-full h-svh">
        {content(toggledSidebar, toggle)}
      </div>
    </>
  );
}
