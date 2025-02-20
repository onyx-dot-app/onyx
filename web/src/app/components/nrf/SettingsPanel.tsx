import React from "react";
import { Switch } from "@/components/ui/switch";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Label } from "@/components/ui/label";
import { useNRFPreferences } from "../../../components/context/NRFPreferencesContext";
import {
  darkExtensionImages,
  lightExtensionImages,
} from "@/lib/extension/constants";

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
    <span className="text-sm text-text-300">{label}</span>
    <Switch
      checked={checked}
      onCheckedChange={onCheckedChange}
      className="data-[state=checked]:bg-white data-[state=checked]:border-background-200 data-[state=unchecked]:bg-background-600"
      circleClassName="data-[state=checked]:bg-background-200"
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
      className="mt-1 border border-background-600 data-[state=checked]:border-white data-[state=checked]:bg-white"
    />
    <Label htmlFor={value} className="flex flex-col">
      <span className="text-sm text-text-300">{label}</span>
      {description && (
        <span className="text-xs text-text-500">{description}</span>
      )}
    </Label>
  </div>
);

export const SettingsPanel = ({
  settingsOpen,
  toggleSettings,
  handleUseOnyxToggle,
}: {
  settingsOpen: boolean;
  toggleSettings: () => void;
  handleUseOnyxToggle: (checked: boolean) => void;
}) => {
  const {
    theme,
    setTheme,
    defaultLightBackgroundUrl,
    setDefaultLightBackgroundUrl,
    defaultDarkBackgroundUrl,
    setDefaultDarkBackgroundUrl,
    useOnyxAsNewTab,
    showShortcuts,
    setShowShortcuts,
  } = useNRFPreferences();

  const toggleTheme = (newTheme: string) => {
    setTheme(newTheme);
  };

  const updateBackgroundUrl = (url: string) => {
    if (theme === "light") {
      setDefaultLightBackgroundUrl(url);
    } else {
      setDefaultDarkBackgroundUrl(url);
    }
  };

  return (
    <div
      className="fixed top-0 right-0 w-[360px] h-full bg-background-800 text-text-300 overflow-y-auto z-20 transition-transform duration-300 ease-in-out transform"
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
            className="text-text-400 hover:text-white"
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
          checked={showShortcuts}
          onCheckedChange={setShowShortcuts}
          label="Show bookmarks"
        />

        <h3 className="text-sm font-semibold mt-6 mb-2">Theme</h3>
        <RadioGroup
          value={theme}
          onValueChange={toggleTheme}
          className="space-y-2"
        >
          <RadioOption
            value="light"
            label="Light theme"
            description="Light theme"
            groupValue={theme}
            onChange={toggleTheme}
          />
          <RadioOption
            value="dark"
            label="Dark theme"
            description="Dark theme"
            groupValue={theme}
            onChange={toggleTheme}
          />
        </RadioGroup>

        <h3 className="text-sm font-semibold mt-6 mb-2">Background</h3>
        <div className="grid grid-cols-4 gap-2">
          {(theme === "dark" ? darkExtensionImages : lightExtensionImages).map(
            (bg: string, index: number) => (
              <div
                key={bg}
                onClick={() => updateBackgroundUrl(bg)}
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
                {(theme === "light"
                  ? defaultLightBackgroundUrl
                  : defaultDarkBackgroundUrl) === bg && (
                  <div className="absolute inset-0 border-2 border-blue-400 rounded" />
                )}
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
};
