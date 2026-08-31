"use client";

import { Switch } from "@opal/components";
import { useNRFPreferences } from "@/components/context/NRFPreferencesContext";
import Text from "@/refresh-components/texts/Text";
import { SvgX, SvgSettings, SvgSun, SvgMoon, SvgCheck } from "@opal/icons";
import { Button } from "@opal/components";
import { cn } from "@opal/utils";
import { useUser } from "@/providers/UserProvider";
import { useTheme } from "next-themes";
import {
  CHAT_BACKGROUND_OPTIONS,
  CHAT_BACKGROUND_NONE,
  ChatBackgroundOption,
} from "@/lib/constants/chatBackgrounds";
import { ThemePreference } from "@/lib/types";
import { useTranslations } from "next-intl";

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
}: BackgroundThumbnailProps) => {
  const t = useTranslations("chat");
  return (
    /* raw-ok: pre-existing full-bleed image tile with selection ring, Button in components/buttons/button d.ts has no image-fill variant */
    <button
      onClick={onClick}
      className="relative overflow-hidden rounded-xl transition-all aspect-video cursor-pointer border-none p-0 bg-transparent group"
      title={label}
      aria-label={
        isSelected
          ? t("nrf.settingsPanel.backgroundOptionSelected.ariaLabel", { label })
          : t("nrf.settingsPanel.backgroundOption.ariaLabel", { label })
      }
    >
      {isNone ? (
        <div className="absolute inset-0 bg-background flex items-center justify-center">
          <Text secondaryBody text03>
            {t("nrf.settingsPanel.backgroundNone.label")}
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
        <div className="absolute top-2 end-2 w-5 h-5 rounded-full bg-theme-primary-05 flex items-center justify-center">
          <SvgCheck className="w-3 h-3 stroke-text-inverted-05" />
        </div>
      )}
    </button>
  );
};

export const SettingsPanel = ({
  settingsOpen,
  toggleSettings,
  handleUseOnyxToggle,
}: {
  settingsOpen: boolean;
  toggleSettings: () => void;
  handleUseOnyxToggle: (checked: boolean) => void;
}) => {
  const tBg = useTranslations("common.chatBackgrounds");
  const bgLabels: Record<string, string> = {
    none: tBg("none.label"),
    clouds: tBg("clouds.label"),
    hills: tBg("hills.label"),
    plant: tBg("plant.label"),
    mountains: tBg("mountains.label"),
    night: tBg("night.label"),
  };
  const t = useTranslations("chat");
  const { useOnyxAsNewTab } = useNRFPreferences();
  const { theme, setTheme } = useTheme();
  const { user, updateUserChatBackground, updateUserThemePreference } =
    useUser();

  const currentBackgroundId = user?.preferences?.chat_background ?? "none";
  const isDark = theme === "dark";

  const toggleTheme = async () => {
    const nextTheme = isDark ? ThemePreference.LIGHT : ThemePreference.DARK;
    setTheme(nextTheme);
    try {
      await updateUserThemePreference(nextTheme);
    } catch {
      // errors are already logged and state is rolled back via refreshUser
      // inside updateUserThemePreference
    }
  };

  const handleBackgroundChange = async (bg: ChatBackgroundOption) => {
    try {
      await updateUserChatBackground(
        bg.id === CHAT_BACKGROUND_NONE ? null : bg.id
      );
      if (bg.theme) {
        setTheme(bg.theme);
        await updateUserThemePreference(bg.theme);
      }
    } catch {
      // errors are already logged and state is rolled back via refreshUser
      // inside the update functions
    }
  };

  return (
    <>
      {/* Backdrop overlay — pointer convenience; the panel closes via keyboard. */}
      <div
        role="presentation"
        className={cn(
          "fixed inset-0 bg-mask-03 backdrop-blur-xs z-40 transition-opacity duration-300",
          settingsOpen
            ? "opacity-100 pointer-events-auto"
            : "opacity-0 pointer-events-none"
        )}
        onClick={toggleSettings}
      />

      {/* Settings panel */}
      <div
        className={cn(
          "fixed top-0 end-0 w-100 h-full z-50",
          "bg-linear-to-b from-background-tint-02 to-background-tint-01",
          "backdrop-blur-xl border-s border-border-01 overflow-y-auto",
          "transition-transform duration-300 ease-out",
          // rtl: the panel hides toward the inline end, so RTL negates.
          settingsOpen
            ? "translate-x-0"
            : "translate-x-full rtl:-translate-x-full"
        )}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 bg-linear-to-b from-background-tint-02 to-transparent pb-4">
          <div className="flex items-center justify-between px-6 pt-6 pb-2">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-background-tint-02">
                <SvgSettings className="w-5 h-5 stroke-text-03" />
              </div>
              <Text headingH3 text04>
                {t("nrf.settingsPanel.header.title")}
              </Text>
            </div>
            <div className="flex items-center gap-3">
              {/* Theme Toggle */}
              <Button
                icon={isDark ? SvgMoon : SvgSun}
                onClick={toggleTheme}
                prominence="tertiary"
                tooltip={t("nrf.settingsPanel.themeToggle.tooltip", {
                  mode: isDark ? "light" : "dark",
                })}
              />
              <Button
                icon={SvgX}
                onClick={toggleSettings}
                prominence="tertiary"
                tooltip={t("nrf.settingsPanel.closeButton.tooltip")}
              />
            </div>
          </div>
        </div>

        <div className="px-6 pb-8 flex flex-col gap-8">
          {/* General Section */}
          <section className="flex flex-col gap-3">
            <Text secondaryAction text03 className="uppercase tracking-wider">
              {t("nrf.settingsPanel.generalSection.title")}
            </Text>
            <div className="flex flex-col gap-1 bg-background-tint-01 rounded-2xl px-4">
              <SettingRow label={t("nrf.settingsPanel.newTabToggle.label")}>
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
              {t("nrf.settingsPanel.backgroundSection.title")}
            </Text>
            <div className="grid grid-cols-3 gap-2">
              {CHAT_BACKGROUND_OPTIONS.map((bg) => (
                <BackgroundThumbnail
                  key={bg.id}
                  thumbnailUrl={bg.thumbnail}
                  label={bgLabels[bg.id] ?? bg.label}
                  isNone={bg.src === CHAT_BACKGROUND_NONE}
                  isSelected={currentBackgroundId === bg.id}
                  onClick={() => handleBackgroundChange(bg)}
                />
              ))}
            </div>
          </section>
        </div>
      </div>
    </>
  );
};
