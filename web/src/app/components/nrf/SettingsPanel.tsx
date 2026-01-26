"use client";

import Switch from "@/refresh-components/inputs/Switch";
import { useNRFPreferences } from "@/components/context/NRFPreferencesContext";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgX, SvgSettings, SvgSun, SvgMoon, SvgCheck } from "@opal/icons";
import { cn } from "@/lib/utils";
import { useUser } from "@/providers/UserProvider";
import { useTheme } from "next-themes";
import {
  CHAT_BACKGROUND_OPTIONS,
  CHAT_BACKGROUND_NONE,
} from "@/lib/constants/chatBackgrounds";

interface SettingRowProps {
  label: string;
  description?: string;
  children: React.ReactNode;
}

const SettingRow = ({ label, description, children }: SettingRowProps) => (
  <div className="flex justify-between items-center py-3">
    <div className="flex flex-col gap-0.5">
      <Text mainUiBody text04>
        {label}
      </Text>
      {description && (
        <Text secondaryBody text03>
          {description}
        </Text>
      )}
    </div>
    {children}
  </div>
);

interface BackgroundThumbnailProps {
  thumbnailUrl: string;
  label: string;
  isNone?: boolean;
  isSelected: boolean;
  onClick: () => void;
}

const BackgroundThumbnail = ({
  thumbnailUrl,
  label,
  isNone = false,
  isSelected,
  onClick,
}: BackgroundThumbnailProps) => (
  <button
    onClick={onClick}
    className="relative overflow-hidden rounded-xl transition-all aspect-video cursor-pointer border-none p-0 bg-transparent group"
    title={label}
    aria-label={`${label} background${isSelected ? " (selected)" : ""}`}
  >
    {isNone ? (
      <div className="absolute inset-0 bg-background flex items-center justify-center">
        <Text secondaryBody text03>
          None
        </Text>
      </div>
    ) : (
      <div
        className="absolute inset-0 bg-cover bg-center transition-transform duration-300 group-hover:scale-105"
        style={{ backgroundImage: `url(${thumbnailUrl})` }}
      />
    )}
    <div
      className={cn(
        "absolute inset-0 transition-all rounded-xl",
        isSelected
          ? "ring-2 ring-inset ring-theme-primary-05"
          : "ring-1 ring-inset ring-border-02 group-hover:ring-border-03"
      )}
    />
    {isSelected && (
      <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-theme-primary-05 flex items-center justify-center">
        <SvgCheck className="w-3 h-3 stroke-text-inverted-05" />
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
  const { useOnyxAsNewTab } = useNRFPreferences();
  const { theme, setTheme } = useTheme();
  const { user, updateUserChatBackground } = useUser();

  const currentBackgroundId = user?.preferences?.chat_background ?? "none";
  const isDark = theme === "dark";

  const toggleTheme = () => {
    setTheme(isDark ? "light" : "dark");
  };

  const handleBackgroundChange = (backgroundId: string) => {
    updateUserChatBackground(
      backgroundId === CHAT_BACKGROUND_NONE ? null : backgroundId
    );
  };

  return (
    <>
      {/* Backdrop overlay */}
      <div
        className={cn(
          "fixed inset-0 bg-mask-03 backdrop-blur-sm z-40 transition-opacity duration-300",
          settingsOpen
            ? "opacity-100 pointer-events-auto"
            : "opacity-0 pointer-events-none"
        )}
        onClick={toggleSettings}
      />

      {/* Settings panel */}
      <div
        className={cn(
          "fixed top-0 right-0 w-[25rem] h-full z-50",
          "bg-gradient-to-b from-background-tint-02 to-background-tint-01",
          "backdrop-blur-[24px] border-l border-border-01 overflow-y-auto",
          "transition-transform duration-300 ease-out",
          settingsOpen ? "translate-x-0" : "translate-x-full"
        )}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 bg-gradient-to-b from-background-tint-02 to-transparent pb-4">
          <div className="flex items-center justify-between px-6 pt-6 pb-2">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-background-tint-02">
                <SvgSettings className="w-5 h-5 stroke-text-03" />
              </div>
              <Text headingH3 text04>
                Settings
              </Text>
            </div>
            <div className="flex items-center gap-3">
              {/* Theme Toggle */}
              <IconButton
                icon={isDark ? SvgMoon : SvgSun}
                onClick={toggleTheme}
                tertiary
                tooltip={`Switch to ${isDark ? "light" : "dark"} theme`}
              />
              <IconButton
                icon={SvgX}
                onClick={toggleSettings}
                tertiary
                tooltip="Close settings"
              />
            </div>
          </div>
        </div>

        <div className="px-6 pb-8 flex flex-col gap-8">
          {/* General Section */}
          <section className="flex flex-col gap-3">
            <Text secondaryAction text03 className="uppercase tracking-wider">
              General
            </Text>
            <div className="flex flex-col gap-1 bg-background-tint-01 rounded-2xl px-4">
              <SettingRow label="Use Onyx as new tab page">
                <Switch
                  checked={useOnyxAsNewTab}
                  onCheckedChange={handleUseOnyxToggle}
                />
              </SettingRow>
            </div>
          </section>

          {/* Background Section */}
          <section className="flex flex-col gap-3">
            <Text secondaryAction text03 className="uppercase tracking-wider">
              Background
            </Text>
            <div className="grid grid-cols-3 gap-2">
              {CHAT_BACKGROUND_OPTIONS.map((bg) => (
                <BackgroundThumbnail
                  key={bg.id}
                  thumbnailUrl={bg.thumbnail}
                  label={bg.label}
                  isNone={bg.url === CHAT_BACKGROUND_NONE}
                  isSelected={currentBackgroundId === bg.id}
                  onClick={() => handleBackgroundChange(bg.id)}
                />
              ))}
            </div>
          </section>
        </div>
      </div>
    </>
  );
};
