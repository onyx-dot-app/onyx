import React, {
  useState,
  useEffect,
  useRef,
  Dispatch,
  SetStateAction,
} from "react";
import FixedLogo from "../chat/shared_chat_search/FixedLogo";
import { ChatInputBar } from "../chat/input/ChatInputBar";
import { Switch } from "@/components/ui/switch";
import { useUser } from "@/components/user/UserProvider";
import { ApiKeyModal } from "@/components/llm/ApiKeyModal";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useAssistants } from "@/components/context/AssistantsContext";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectTrigger,
  SelectContent,
  SelectItem,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { SimplifiedChatInputBar } from "../chat/input/SimplifiedChatInputBar";
import { Hamburger } from "@phosphor-icons/react";
import { Menu } from "lucide-react";

const SidebarSwitch = ({
  checked,
  onCheckedChange,
  label,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
}) => (
  <div className="flex justify-between items-center py-2">
    <span className="text-sm text-gray-300">{label}</span>
    <Switch
      checked={checked}
      onCheckedChange={onCheckedChange}
      className="data-[state=checked]:bg-white data-[state=unchecked]:bg-gray-600"
    />
  </div>
);

const RadioOption = ({
  value,
  label,
  description,
  groupValue,
  onChange,
}: {
  value: string;
  label: string;
  description: string;
  groupValue: string;
  onChange: (value: string) => void;
}) => (
  <div className="flex items-start space-x-2 mb-2">
    <RadioGroupItem
      value={value}
      id={value}
      className="mt-1 border border-gray-600 data-[state=checked]:border-white data-[state=checked]:bg-white"
    />
    <Label htmlFor={value} className="flex flex-col">
      <span className="text-sm text-gray-300">{label}</span>
      {description && (
        <span className="text-xs text-gray-500">{description}</span>
      )}
    </Label>
  </div>
);

export default function NRFPageNewDesign() {
  const { popup, setPopup } = usePopup();
  const { assistants } = useAssistants();

  const [message, setMessage] = useState("");
  const textAreaRef = useRef<HTMLTextAreaElement | null>(null);
  const darkImages = [
    "https://images.unsplash.com/photo-1692520883599-d543cfe6d43d?q=80&w=2666&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
    "https://images.unsplash.com/photo-1520330461350-508fab483d6a?q=80&w=2723&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
  ];

  const lightImages = [
    "https://images.unsplash.com/photo-1473830439578-14e9a9e61d55?q=80&w=2670&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
    "https://images.unsplash.com/photo-1500964757637-c85e8a162699?q=80&w=2703&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
    "https://images.unsplash.com/photo-1475924156734-496f6cac6ec1?q=80&w=2670&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
  ];

  // Whether or not Onyx is used as the default new tab
  const [useOnyxAsNewTab, setUseOnyxAsNewTab] = useState<boolean>(() => {
    return localStorage.getItem("useOnyxAsNewTab") === "true";
  });

  // Show modal to confirm turning off Onyx as new tab
  const [showTurnOffModal, setShowTurnOffModal] = useState<boolean>(false);

  // Settings sidebar open/close go
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);

  const [showBookmarksBar, setShowBookmarksBar] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [newTabPageView, setNewTabPageView] = useState(
    localStorage.getItem("newTabPageView") || "simple"
  );

  enum LightBackgroundColors {
    RED = "#FFB3BA",
    BLUE = "#BAEEFF",
    GREEN = "#BAFFC9",
    YELLOW = "#FFFFBA",
    PURPLE = "#E2BAFF",
    ORANGE = "#FFD8B3",
    PINK = "#FFC9DE",
  }

  enum DarkBackgroundColors {
    RED = "#8B0000",
    BLUE = "#000080",
    GREEN = "#006400",
    YELLOW = "#8B8000",
    PURPLE = "#4B0082",
    ORANGE = "#FF8C00",
    PINK = "#FF1493",
  }

  enum StoredBackgroundColors {
    RED = "Red",
    BLUE = "Blue",
    GREEN = "Green",
    YELLOW = "Yellow",
    PURPLE = "Purple",
    ORANGE = "Orange",
    PINK = "Pink",
  }
  type BackgroundColors = LightBackgroundColors | DarkBackgroundColors;

  interface Shortcut {
    name: string;
    url: string;
    backgroundColor: StoredBackgroundColors;
  }

  const [shortCuts, setShortCuts] = useState<Shortcut[]>(
    JSON.parse(localStorage.getItem("shortCuts") || "[]")
  );

  const [theme, setTheme] = useState(() => {
    return localStorage.getItem("onyxTheme") || "dark";
  });

  const toggleTheme = (theme: string) => {
    setTheme(theme);
    localStorage.setItem("onyxTheme", theme);
    if (theme === "light") {
      setBackgroundUrl(lightImages[0]);
    } else {
      setBackgroundUrl(darkImages[0]);
    }
  };

  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Focus the input bar on component mount
    if (inputRef.current) {
      inputRef.current.focus();
    }
  }, []);

  const [inputValue, setInputValue] = useState("");

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(e.target.value);
  };

  const handleInputSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Handle the input submission here
    console.log("Input submitted:", inputValue);
    setInputValue("");
  };

  // Saved background in localStorage
  const [backgroundUrl, setBackgroundUrl] = useState<string>(() => {
    return (
      localStorage.getItem(
        theme === "light" ? "onyxBackgroundLight" : "onyxBackgroundDark"
      ) ||
      "https://images.unsplash.com/photo-1548613112-7455315eef5f?q=80&w=2787&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D"
    );
  });

  useEffect(() => {
    localStorage.setItem("shortCuts", JSON.stringify(shortCuts));
  }, [shortCuts]);

  useEffect(() => {
    localStorage.setItem("newTabPageView", newTabPageView);
  }, [newTabPageView]);

  useEffect(() => {
    localStorage.setItem("useOnyxAsNewTab", String(useOnyxAsNewTab));
  }, [useOnyxAsNewTab]);

  const onSubmit = async ({
    messageOverride,
  }: {
    messageOverride?: string;
  } = {}) => {
    const userMessage = messageOverride || message;
    console.log("User message:", userMessage);
    setMessage("");

    setPopup({
      message: `Message submitted: ${userMessage}`,
      type: "success",
    });
  };

  const ShortCut = ({ shortCut }: { shortCut: Shortcut }) => {
    return (
      <div
        onClick={() => {
          window.open(shortCut.url, "_blank");
        }}
        className="w-20 h-20 rounded-lg"
        style={{
          backgroundColor: shortCut.backgroundColor,
        }}
      >
        <h1>{shortCut.name}</h1>
      </div>
    );
  };

  const AddShortCut = ({
    openShortCutModal,
  }: {
    openShortCutModal: () => void;
  }) => {
    return (
      <button
        onClick={openShortCutModal}
        className="w-20 h-20 rounded-lg bg-white/70 hover:bg-white/50 backdrop-blur-sm p-2 rounded-lg"
      >
        <h1 className="text-neutral-900 text-xs">New Bookmark</h1>
      </button>
    );
  };
  // Toggle sidebar
  const toggleSettings = () => {
    setSettingsOpen((prev) => !prev);
  };

  // If user toggles the "Use Onyx" switch to off, prompt a modal
  const handleUseOnyxToggle = (checked: boolean) => {
    if (!checked) {
      setShowTurnOffModal(true);
    } else {
      setUseOnyxAsNewTab(true);
    }
  };

  // Confirm turning off Onyx
  const confirmTurnOff = () => {
    setUseOnyxAsNewTab(false);
    setShowTurnOffModal(false);
  };
  const NewShortCutModal = ({
    isOpen,
    onClose,
    onAdd,
  }: {
    isOpen: boolean;
    onClose: () => void;
    onAdd: (shortcut: Shortcut) => void;
  }) => {
    const [name, setName] = useState("");
    const [url, setUrl] = useState("");
    const [backgroundColor, setBackgroundColor] =
      useState<StoredBackgroundColors>(StoredBackgroundColors.BLUE);

    const handleSubmit = (e: React.FormEvent) => {
      e.preventDefault();
      onAdd({ name, url, backgroundColor });
      onClose();
    };

    return (
      <Dialog open={isOpen} onOpenChange={onClose}>
        <DialogContent className="max-w-[95%] sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>Add New Shortcut</DialogTitle>
            <DialogDescription>
              Create a new shortcut for quick access to your favorite websites.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="w-full  grid gap-4 py-4">
              <div className="text-xs grid grid-cols-7 w-full items-center gap-2">
                <Label htmlFor="name" className="text-right">
                  Name
                </Label>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="col-span-5 border-neutral-700"
                />
              </div>
              <div className="grid w-full grid-cols-7 items-center gap-4">
                <Label htmlFor="url" className="text-right">
                  URL
                </Label>
                <Input
                  id="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  className="col-span-5 border-neutral-700"
                />
              </div>
              <div className="grid grid-cols-7 w-full items-center gap-4">
                <Label htmlFor="color" className="text-right">
                  Color
                </Label>
                <Select
                  onValueChange={(value: StoredBackgroundColors) =>
                    setBackgroundColor(value)
                  }
                >
                  <SelectTrigger className="col-span-5 flex items-center">
                    <div
                      className="w-3 h-3 rounded-sm mr-2"
                      style={{ backgroundColor }}
                    ></div>
                    <SelectValue placeholder="Select a color" />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.values(StoredBackgroundColors).map((color) => (
                      <SelectItem
                        className="relative"
                        key={color}
                        value={color}
                      >
                        <div className="flex items-center">
                          <div
                            className="w-3 h-3 absolute left-2 top-1/2 transform -translate-y-1/2 rounded-sm mr-2"
                            style={{ backgroundColor: color }}
                          ></div>
                          {color}
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button type="submit">Add Shortcut</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  };

  const [showShortCutModal, setShowShortCutModal] = useState(false);

  return (
    <div
      className="relative w-full h-full flex flex-col"
      style={{
        minHeight: "100vh",
        background: `url(${backgroundUrl}) no-repeat center center / cover`,
        overflow: "hidden",
      }}
    >
      {/* Top bar with settings icon */}
      <div
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          padding: "16px",
          zIndex: 10,
        }}
      >
        <button
          aria-label="Open settings"
          onClick={toggleSettings}
          style={{
            background: "rgba(255, 255, 255, 0.7)",
            border: "none",
            borderRadius: "50%",
            padding: "10px",
            cursor: "pointer",
          }}
        >
          <Menu size={12} className="text-neutral-900" />
        </button>
      </div>

      {/* Simplified center section */}
      <div className="absolute top-[40%] left-1/2 -translate-x-1/2 -translate-y-1/2 text-center w-[90%]  lg:max-w-3xl">
        <h1
          className={`pl-2 text-xl text-left w-full mb-4 ${
            theme === "light" ? "text-neutral-800" : "text-white"
          }`}
        >
          Start your day with Onyx
        </h1>

        <SimplifiedChatInputBar
          removeFilters={() => {}}
          removeDocs={() => {}}
          openModelSettings={() => {}}
          showConfigureAPIKey={() => {}}
          chatState="input"
          stopGenerating={() => {}}
          onSubmit={onSubmit}
          selectedAssistant={assistants[0]}
          setSelectedAssistant={() => {}}
          setAlternativeAssistant={() => {}}
          alternativeAssistant={null}
          selectedDocuments={[]}
          showDocs={() => {}}
          handleFileUpload={() => {}}
          message={message}
          setMessage={setMessage}
          llmOverrideManager={null as any}
          files={[]}
          setFiles={() => {}}
          textAreaRef={textAreaRef}
          chatSessionId="onyx-new-design"
        />

        {showShortcuts && (
          <div className="grid flex grid-cols-4 mt-20 gap-4">
            {shortCuts.map((shortCut) => (
              <ShortCut shortCut={shortCut} />
            ))}
            <AddShortCut openShortCutModal={() => setShowShortCutModal(true)} />
          </div>
        )}
      </div>

      {showShortCutModal && (
        <NewShortCutModal
          isOpen={showShortCutModal}
          onClose={() => setShowShortCutModal(false)}
          onAdd={(shortCut) => {
            setShortCuts([...shortCuts, shortCut]);
            setShowShortCutModal(false);
          }}
        />
      )}
      {/* {newTabPageView && } */}

      {/* Bottom-right container for the "Use Onyx as new tab" toggle */}
      <div className="absolute bottom-4 right-4 z-10 flex items-center bg-white/80 backdrop-blur-sm p-2 rounded-lg">
        <label
          htmlFor="useOnyx"
          className="cursor-pointer mr-2 text-black text-xs font-medium"
        >
          Use Onyx as default new tab
        </label>
        <Switch
          id="useOnyx"
          checked={useOnyxAsNewTab}
          onCheckedChange={(val) => handleUseOnyxToggle(val)}
        />
      </div>

      {/* Improved slide-in settings sidebar */}
      <div
        className="fixed top-0 right-0 w-[360px] h-full bg-[#202124] text-gray-300 overflow-y-auto z-20 transition-transform duration-300 ease-in-out transform"
        style={{
          transform: settingsOpen ? "translateX(0)" : "translateX(100%)",
          boxShadow: "-2px 0 10px rgba(0,0,0,0.3)",
        }}
      >
        <div className="p-6">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-xl font-semibold text-white">
              Home page settings
            </h2>
            <button
              aria-label="Close"
              onClick={toggleSettings}
              className="text-gray-400 hover:text-white"
            >
              ✕
            </button>
          </div>

          <h3 className="text-sm font-semibold mb-2">General</h3>
          <SidebarSwitch
            checked={useOnyxAsNewTab}
            onCheckedChange={handleUseOnyxToggle}
            label="Use Onyx as new tab page"
          />
          <SidebarSwitch
            checked={showBookmarksBar}
            onCheckedChange={setShowBookmarksBar}
            label="Show bookmarks bar"
          />
          <SidebarSwitch
            checked={showShortcuts}
            onCheckedChange={setShowShortcuts}
            label="Show shortcuts"
          />

          <h3 className="text-sm font-semibold mt-6 mb-2">New Tab Page View</h3>
          <RadioGroup
            value={newTabPageView}
            onValueChange={setNewTabPageView}
            className="space-y-2"
          >
            <RadioOption
              value="simple"
              label="Simple"
              description="Minimal and focused."
              groupValue={newTabPageView}
              onChange={setNewTabPageView}
            />
            <RadioOption
              value="informational"
              label="Informational"
              description="Show widgets like calendar, mentions, and more."
              groupValue={newTabPageView}
              onChange={setNewTabPageView}
            />
          </RadioGroup>
          <h3 className="text-sm font-semibold mt-6 mb-2">Theme</h3>
          <RadioGroup
            value={theme}
            onValueChange={setTheme}
            className="space-y-2"
          >
            <RadioOption
              value="light"
              label="Light theme"
              description="Light theme"
              groupValue={theme}
              onChange={setTheme}
            />
            <RadioOption
              value="dark"
              label="Dark theme"
              description="Dark theme"
              groupValue={theme}
              onChange={setTheme}
            />
            <RadioOption
              value="sync"
              label="Sync with device"
              description="Sync with device"
              groupValue={theme}
              onChange={setTheme}
            />
          </RadioGroup>

          <h3 className="text-sm font-semibold mt-6 mb-2">Background</h3>
          <div className="grid grid-cols-4 gap-2">
            {(theme === "dark" ? darkImages : lightImages).map((bg, index) => (
              <div
                key={bg}
                onClick={() => setBackgroundUrl(bg)}
                className={`relative ${
                  index === 0 ? "col-span-2 row-span-2" : ""
                } cursor-pointer rounded-sm overflow-hidden`}
                style={{
                  paddingBottom: index === 0 ? "100%" : "50%",
                }}
              >
                <div
                  className="absolute inset-0 bg-cover bg-center"
                  style={{ backgroundImage: `url(${bg})` }}
                />
                {backgroundUrl === bg && (
                  <div className="absolute inset-0 border-2 border-blue-400 rounded" />
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Modal for confirming turn off */}
      <Dialog open={showTurnOffModal} onOpenChange={setShowTurnOffModal}>
        <DialogContent className="w-fit max-w-[95%]">
          <DialogHeader>
            <DialogTitle>Turn off Onyx new tab page?</DialogTitle>
            <DialogDescription>
              You’ll see your browser’s default new tab page instead.
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

      {/* If you have or need an API Key modal */}
      {false && (
        <ApiKeyModal
          hide={() => {
            /* handle close */
          }}
          setPopup={setPopup}
        />
      )}

      {popup}
    </div>
  );
}
