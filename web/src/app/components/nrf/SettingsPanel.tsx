"use client";

import Switch from "@/refresh-components/inputs/Switch";
import { useNRFPreferences } from "../../../components/context/NRFPreferencesContext";
import {
  darkExtensionImages,
  lightExtensionImages,
} from "@/lib/extension/constants";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgX } from "@opal/icons";
import { SvgSettings } from "@opal/icons";
import { SvgSun } from "@opal/icons";
import { SvgMoon } from "@opal/icons";
import { cn } from "@/lib/utils";

interface SettingRowProps {
  label: string;
  description?: string;
  children: React.ReactNode;
}

const SettingRow = ({ label, description, children }: SettingRowProps) => (
  <div className="flex justify-between items-center py-3">
    <div className="flex flex-col gap-0.5">
      <Text mainUiBody textLight05>
        {label}
      </Text>
      {description && (
        <Text secondaryBody textLight03>
          {description}
        </Text>
      )}
    </div>
    {children}
  </div>
);

interface BackgroundThumbnailProps {
  url: string;
  isSelected: boolean;
  onClick: () => void;
}

const BackgroundThumbnail = ({
  url,
  isSelected,
  onClick,
}: BackgroundThumbnailProps) => (
  <button
    onClick={onClick}
    className={cn(
      "relative overflow-hidden rounded-12 transition-all duration-200",
      "aspect-[16/9]",
      "group"
    )}
  >
    <div
      className="absolute inset-0 bg-cover bg-center transition-transform duration-300 group-hover:scale-105"
      style={{ backgroundImage: `url(${url})` }}
    />
    <div
      className={cn(
        "absolute inset-0 transition-all duration-200",
        isSelected
          ? "ring-2 ring-inset ring-white/80"
          : "ring-1 ring-inset ring-white/20 group-hover:ring-white/40"
      )}
      style={{ borderRadius: "inherit" }}
    />
    {isSelected && (
      <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-white flex items-center justify-center">
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          className="text-background-800"
        >
          <path
            d="M10 3L4.5 8.5L2 6"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    )}
  </button>
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

  const currentBackgroundUrl =
    theme === "light" ? defaultLightBackgroundUrl : defaultDarkBackgroundUrl;
  const backgroundImages =
    theme === "dark" ? darkExtensionImages : lightExtensionImages;

  return (
    <>
      {/* Backdrop overlay */}
      <div
        className={cn(
          "fixed inset-0 bg-black/40 backdrop-blur-sm z-40 transition-opacity duration-300",
          settingsOpen
            ? "opacity-100 pointer-events-auto"
            : "opacity-0 pointer-events-none"
        )}
        onClick={toggleSettings}
      />

      {/* Settings panel */}
      <div
        className={cn(
          "fixed top-0 right-0 w-[400px] h-full z-50",
          "bg-gradient-to-b from-background-900/95 to-background-800/95",
          "backdrop-blur-xl",
          "border-l border-white/10",
          "overflow-y-auto",
          "transition-transform duration-300 ease-out",
          settingsOpen ? "translate-x-0" : "translate-x-full"
        )}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 bg-gradient-to-b from-background-900/95 to-transparent pb-4">
          <div className="flex items-center justify-between p-6 pb-2">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-10 h-10 rounded-12 bg-white/10">
                <SvgSettings size={20} className="text-white" />
              </div>
              <Text headingH3 textLight05>
                Settings
              </Text>
            </div>
            <div className="flex items-center gap-3">
              {/* Theme Toggle */}
              <button
                onClick={() =>
                  toggleTheme(theme === "light" ? "dark" : "light")
                }
                className={cn(
                  "flex items-center gap-2 px-3 py-1.5 rounded-full transition-all duration-200",
                  "bg-white/10 hover:bg-white/15 border border-white/10"
                )}
                aria-label={`Switch to ${
                  theme === "light" ? "dark" : "light"
                } theme`}
              >
                {theme === "light" ? (
                  <SvgSun size={16} className="text-white" />
                ) : (
                  <SvgMoon size={16} className="text-white" />
                )}
              </button>
              <IconButton
                icon={SvgX}
                onClick={toggleSettings}
                tertiary
                className="hover:bg-white/10"
              />
            </div>
          </div>
        </div>

        <div className="px-6 pb-8 space-y-8">
          {/* General Section */}
          <section>
            <Text
              secondaryAction
              textLight03
              className="uppercase tracking-wider mb-3"
            >
              General
            </Text>
            <div className="space-y-1 bg-white/5 rounded-16 px-4">
              <SettingRow label="Use Onyx as new tab page">
                <Switch
                  checked={useOnyxAsNewTab}
                  onCheckedChange={handleUseOnyxToggle}
                />
              </SettingRow>
            </div>
          </section>

          {/* Background Section */}
          <section>
            <Text
              secondaryAction
              textLight03
              className="uppercase tracking-wider mb-3"
            >
              Background
            </Text>
            <div className="grid grid-cols-3 gap-2">
              {backgroundImages.map((bg: string) => (
                <BackgroundThumbnail
                  key={bg}
                  url={bg}
                  isSelected={currentBackgroundUrl === bg}
                  onClick={() => updateBackgroundUrl(bg)}
                />
              ))}
            </div>
          </section>
        </div>
      </div>
    </>
  );
};
