"use client";

import Cookies from "js-cookie";
import { SIDEBAR_TOGGLED_COOKIE_NAME } from "@/components/resizable/constants";
import {
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useSidebarVisibility } from "@/components/chat/hooks";
import FunctionalHeader from "@/components/chat/Header";
import { useRouter } from "next/navigation";
import { pageType } from "../chat/sessionSidebar/types";
import FixedLogo from "../../components/logo/FixedLogo";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { useChatContext } from "@/components/context/ChatContext";
import { HistorySidebar } from "../chat/sessionSidebar/HistorySidebar";
import { useAssistants } from "@/components/context/AssistantsContext";
import AssistantModal from "./mine/AssistantModal";
import { useSidebarShortcut } from "@/lib/browserUtilities";

interface SidebarWrapperProps<T extends object> {
  initiallyToggled: boolean;
  size?: "sm" | "lg";
  children: ReactNode;
}

export default function SidebarWrapper<T extends object>({
  initiallyToggled,
  size = "sm",
  children,
}: SidebarWrapperProps<T>) {
  const [sidebarVisible, setSidebarVisible] = useState(initiallyToggled);
  const [showDocSidebar, setShowDocSidebar] = useState(false); // State to track if sidebar is open
  // Used to maintain a "time out" for history sidebar so our existing refs can have time to process change
  const [untoggled, setUntoggled] = useState(false);

  const toggleSidebar = useCallback(() => {
    Cookies.set(
      SIDEBAR_TOGGLED_COOKIE_NAME,
      String(!sidebarVisible).toLocaleLowerCase()
    ),
      {
        path: "/",
      };
    setSidebarVisible((sidebarVisible) => !sidebarVisible);
  }, [sidebarVisible]);

  const sidebarElementRef = useRef<HTMLDivElement>(null);
  const { folders, openedFolders, chatSessions } = useChatContext();
  const { assistants } = useAssistants();
  const explicitlyUntoggle = () => {
    setShowDocSidebar(false);

    setUntoggled(true);
    setTimeout(() => {
      setUntoggled(false);
    }, 200);
  };

  const settings = useContext(SettingsContext);
  useSidebarVisibility({
    sidebarVisible,
    sidebarElementRef,
    showDocSidebar,
    setShowDocSidebar,
    mobile: settings?.isMobile,
  });

  const [showAssistantsModal, setShowAssistantsModal] = useState(false);
  const router = useRouter();

  useSidebarShortcut(router, toggleSidebar);

  return (
    <div className="flex relative overflow-x-hidden overscroll-contain flex-col w-full h-screen">
      {showAssistantsModal && (
        <AssistantModal hideModal={() => setShowAssistantsModal(false)} />
      )}
      <div
        ref={sidebarElementRef}
        className={`
            flex-none
            fixed
            left-0
            z-30
            bg-background-100
            h-screen
            transition-all
            bg-opacity-80
            duration-300
            ease-in-out
            ${
              !untoggled && (showDocSidebar || sidebarVisible)
                ? "opacity-100 w-[250px] translate-x-0"
                : "opacity-0 w-[200px] pointer-events-none -translate-x-10"
            }`}
      >
        <div className="w-full relative">
          {" "}
          <HistorySidebar
            setShowAssistantsModal={setShowAssistantsModal}
            page={"chat"}
            explicitlyUntoggle={explicitlyUntoggle}
            ref={sidebarElementRef}
            toggleSidebar={toggleSidebar}
            toggled={sidebarVisible}
            existingChats={chatSessions}
            currentChatSession={null}
            folders={folders}
          />
        </div>
      </div>

      <div className="absolute px-2 left-0 w-full top-0">
        <FunctionalHeader
          sidebarToggled={sidebarVisible}
          toggleSidebar={toggleSidebar}
          page="chat"
        />
        <div className="w-full flex">
          <div
            style={{ transition: "width 0.30s ease-out" }}
            className={`flex-none
                      overflow-y-hidden
                      bg-background-100
                      h-full
                      transition-all
                      bg-opacity-80
                      duration-300 
                      ease-in-out
                      ${sidebarVisible ? "w-[250px]" : "w-[0px]"}`}
          />

          <div
            className={`mt-4 w-full ${
              size == "lg" ? "max-w-4xl" : "max-w-3xl"
            } mx-auto`}
          >
            {children}
          </div>
        </div>
      </div>
      <FixedLogo backgroundToggled={sidebarVisible || showDocSidebar} />
    </div>
  );
}
