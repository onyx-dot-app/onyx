"use client";
import React, { useState, useEffect, useRef, useContext } from "react";
import { useUser } from "@/components/user/UserProvider";
import { usePopup } from "@/components/admin/connectors/Popup";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { v4 as uuidv4 } from "uuid";
import { Button } from "@/components/ui/button";
import { SimplifiedChatInputBar } from "../components/input/SimplifiedChatInputBar";
import { Menu } from "lucide-react";
import { Shortcut } from "./interfaces";
import {
  MaxShortcutsReachedModal,
  NewShortCutModal,
} from "@/components/extension/Shortcuts";
import { Modal } from "@/components/Modal";
import { useNightTime } from "@/lib/dateUtils";
import { useFilters } from "@/lib/hooks";
import { uploadFilesForChat } from "../services/lib";
import { ChatFileType, FileDescriptor } from "../interfaces";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import Dropzone from "react-dropzone";
import { useSendMessageToParent } from "@/lib/extension/utils";
import { useNRFPreferences } from "@/components/context/NRFPreferencesContext";
import { SettingsPanel } from "../../components/nrf/SettingsPanel";
import { ShortcutsDisplay } from "../../components/nrf/ShortcutsDisplay";
import LoginPage from "../../auth/login/LoginPage";
import { AuthType } from "@/lib/constants";
import { sendSetDefaultNewTabMessage } from "@/lib/extension/utils";
import { ReadonlyRequestCookies } from "next/dist/server/web/spec-extension/adapters/request-cookies";
import { CHROME_MESSAGE } from "@/lib/extension/constants";
import { ApiKeyModal } from "@/components/llm/ApiKeyModal";
import { SettingsContext } from "@/components/settings/SettingsProvider";

export default function NRFPage({
  requestCookies,
}: {
  requestCookies: ReadonlyRequestCookies;
}) {
  const {
    theme,
    defaultLightBackgroundUrl,
    defaultDarkBackgroundUrl,
    shortcuts: shortCuts,
    setShortcuts: setShortCuts,
    setUseOnyxAsNewTab,
    showShortcuts,
  } = useNRFPreferences();

  const filterManager = useFilters();
  const { isNight } = useNightTime();
  const { user } = useUser();
  const { ccPairs, documentSets, tags, llmProviders } = useChatContext();
  const settings = useContext(SettingsContext);

  const { popup, setPopup } = usePopup();

  // State
  const [message, setMessage] = useState("");
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);
  const [editingShortcut, setEditingShortcut] = useState<Shortcut | null>(null);
  const [backgroundUrl, setBackgroundUrl] = useState<string>(
    theme === "light" ? defaultLightBackgroundUrl : defaultDarkBackgroundUrl
  );

  // Modals
  const [showTurnOffModal, setShowTurnOffModal] = useState<boolean>(false);
  const [showShortCutModal, setShowShortCutModal] = useState(false);
  const [showMaxShortcutsModal, setShowMaxShortcutsModal] = useState(false);
  const [showLoginModal, setShowLoginModal] = useState<boolean>(!user);

  // Refs
  const textAreaRef = useRef<HTMLTextAreaElement | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setBackgroundUrl(
      theme === "light" ? defaultLightBackgroundUrl : defaultDarkBackgroundUrl
    );
  }, [theme, defaultLightBackgroundUrl, defaultDarkBackgroundUrl]);

  useSendMessageToParent();
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus();
    }
  }, []);

  const toggleSettings = () => {
    setSettingsOpen((prev) => !prev);
  };

  // If user toggles the "Use Onyx" switch to off, prompt a modal
  const handleUseOnyxToggle = (checked: boolean) => {
    if (!checked) {
      setShowTurnOffModal(true);
    } else {
      setUseOnyxAsNewTab(true);
      sendSetDefaultNewTabMessage(true);
    }
  };

  const availableSources = ccPairs.map((ccPair) => ccPair.source);

  const [currentMessageFiles, setCurrentMessageFiles] = useState<
    FileDescriptor[]
  >([]);

  const handleImageUpload = async (acceptedFiles: File[]) => {
    const tempFileDescriptors = acceptedFiles.map((file) => ({
      id: uuidv4(),
      type: file.type.startsWith("image/")
        ? ChatFileType.IMAGE
        : ChatFileType.DOCUMENT,
      isUploading: true,
    }));

    // only show loading spinner for reasonably large files
    const totalSize = acceptedFiles.reduce((sum, file) => sum + file.size, 0);
    if (totalSize > 50 * 1024) {
      setCurrentMessageFiles((prev) => [...prev, ...tempFileDescriptors]);
    }

    const removeTempFiles = (prev: FileDescriptor[]) => {
      return prev.filter(
        (file) => !tempFileDescriptors.some((newFile) => newFile.id === file.id)
      );
    };

    await uploadFilesForChat(acceptedFiles).then(([files, error]) => {
      if (error) {
        setCurrentMessageFiles((prev) => removeTempFiles(prev));
        setPopup({
          type: "error",
          message: error,
        });
      } else {
        setCurrentMessageFiles((prev) => [...removeTempFiles(prev), ...files]);
      }
    });
  };

  const confirmTurnOff = () => {
    setUseOnyxAsNewTab(false);
    setShowTurnOffModal(false);
    sendSetDefaultNewTabMessage(false);
  };

  // Auth related
  const [authType, setAuthType] = useState<AuthType | null>(null);
  const [fetchingAuth, setFetchingAuth] = useState(false);
  useEffect(() => {
    // If user is already logged in, no need to fetch auth data
    if (user) return;

    async function fetchAuthData() {
      setFetchingAuth(true);

      try {
        const res = await fetch("/api/auth/type", {
          method: "GET",
          credentials: "include",
        });
        if (!res.ok) {
          throw new Error(`Failed to fetch auth type: ${res.statusText}`);
        }

        const data = await res.json();
        setAuthType(data.auth_type);
      } catch (err) {
        console.error("Error fetching auth data:", err);
      } finally {
        setFetchingAuth(false);
      }
    }

    fetchAuthData();
  }, [user]);

  const onSubmit = async ({
    messageOverride,
  }: {
    messageOverride?: string;
  } = {}) => {
    const userMessage = messageOverride || message;

    let filterString = filterManager?.getFilterString();

    if (currentMessageFiles.length > 0) {
      filterString +=
        "&files=" + encodeURIComponent(JSON.stringify(currentMessageFiles));
    }

    const newHref =
      `${settings?.webDomain}/chat?send-on-load=true&user-prompt=` +
      encodeURIComponent(userMessage) +
      filterString;

    if (typeof window !== "undefined" && window.parent) {
      window.parent.postMessage(
        { type: CHROME_MESSAGE.LOAD_NEW_PAGE, href: newHref },
        "*"
      );
    } else {
      window.location.href = newHref;
    }
  };

  return (
    <div
      className="relative w-full h-full flex flex-col min-h-screen bg-cover bg-center bg-no-repeat overflow-hidden transition-[background-image] duration-300 ease-in-out"
      style={{
        backgroundImage: `url(${backgroundUrl})`,
      }}
    >
      <div className="absolute top-0 right-0 p-4 z-10">
        <button
          aria-label="Open settings"
          onClick={toggleSettings}
          className="bg-white bg-opacity-70 rounded-full p-2.5 cursor-pointer hover:bg-opacity-80 transition-colors duration-200"
        >
          <Menu size={12} className="text-text-900" />
        </button>
      </div>

      <Dropzone onDrop={handleImageUpload} noClick>
        {({ getRootProps }) => (
          <div
            {...getRootProps()}
            className="absolute top-20 left-0 w-full h-full flex flex-col"
          >
            <div className="pointer-events-auto absolute top-[40%] left-1/2 -translate-x-1/2 -translate-y-1/2 text-center w-[90%] lg:max-w-3xl">
              <h1
                className={`pl-2 text-xl text-left w-full mb-4 ${
                  theme === "light" ? "text-text-800" : "text-white"
                }`}
              >
                {isNight
                  ? "End your day with Onyx"
                  : "Start your day with Onyx"}
              </h1>

              <SimplifiedChatInputBar
                onSubmit={onSubmit}
                handleFileUpload={handleImageUpload}
                message={message}
                setMessage={setMessage}
                files={currentMessageFiles}
                setFiles={setCurrentMessageFiles}
                filterManager={filterManager}
                textAreaRef={textAreaRef}
                existingSources={availableSources}
                availableDocumentSets={documentSets}
                availableTags={tags}
              />

              <ShortcutsDisplay
                shortCuts={shortCuts}
                showShortcuts={showShortcuts}
                setEditingShortcut={setEditingShortcut}
                setShowShortCutModal={setShowShortCutModal}
                openShortCutModal={() => {
                  if (shortCuts.length >= 6) {
                    setShowMaxShortcutsModal(true);
                  } else {
                    setEditingShortcut(null);
                    setShowShortCutModal(true);
                  }
                }}
              />
            </div>
          </div>
        )}
      </Dropzone>
      {showMaxShortcutsModal && (
        <MaxShortcutsReachedModal
          onClose={() => setShowMaxShortcutsModal(false)}
        />
      )}
      {showShortCutModal && (
        <NewShortCutModal
          setPopup={setPopup}
          onDelete={(shortcut: Shortcut) => {
            setShortCuts(
              shortCuts.filter((s: Shortcut) => s.name !== shortcut.name)
            );
            setShowShortCutModal(false);
          }}
          isOpen={showShortCutModal}
          onClose={() => {
            setEditingShortcut(null);
            setShowShortCutModal(false);
          }}
          onAdd={(shortCut: Shortcut) => {
            if (editingShortcut) {
              setShortCuts(
                shortCuts
                  .filter((s) => s.name !== editingShortcut.name)
                  .concat(shortCut)
              );
            } else {
              setShortCuts([...shortCuts, shortCut]);
            }
            setShowShortCutModal(false);
          }}
          editingShortcut={editingShortcut}
        />
      )}
      <SettingsPanel
        settingsOpen={settingsOpen}
        toggleSettings={toggleSettings}
        handleUseOnyxToggle={handleUseOnyxToggle}
      />

      <Dialog open={showTurnOffModal} onOpenChange={setShowTurnOffModal}>
        <DialogContent className="w-fit max-w-[95%]">
          <DialogHeader>
            <DialogTitle>Turn off Onyx new tab page?</DialogTitle>
            <DialogDescription>
              You&apos;ll see your browser&apos;s default new tab page instead.
              <br />
              You can turn it back on anytime in your Onyx settings.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex gap-2 justify-center">
            <Button
              variant="outline"
              onClick={() => setShowTurnOffModal(false)}
            >
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmTurnOff}>
              Turn off
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {!user && authType !== "disabled" && showLoginModal ? (
        <Modal className="max-w-md mx-auto">
          {fetchingAuth ? (
            <p className="p-4">Loading login info…</p>
          ) : authType == "basic" ? (
            <LoginPage
              authUrl={null}
              authTypeMetadata={{
                authType: authType as AuthType,
                autoRedirect: false,
                requiresVerification: false,
                anonymousUserEnabled: null,
              }}
              nextUrl="/nrf"
            />
          ) : (
            <div className="flex flex-col items-center">
              <h2 className="text-center text-xl text-strong font-bold mb-4">
                Welcome to Onyx
              </h2>
              <Button
                className="bg-agent w-full hover:bg-accent-hover text-white"
                onClick={() => {
                  if (window.top) {
                    window.top.location.href = "/auth/login";
                  } else {
                    window.location.href = "/auth/login";
                  }
                }}
              >
                Log in
              </Button>
            </div>
          )}
        </Modal>
      ) : (
        llmProviders.length == 0 && <ApiKeyModal setPopup={setPopup} />
      )}
    </div>
  );
}
