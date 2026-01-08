"use client";

import Switch from "@/refresh-components/inputs/Switch";
import { useNRFPreferences } from "@/components/context/NRFPreferencesContext";
import {
  darkExtensionImages,
  lightExtensionImages,
} from "@/lib/extension/constants";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgX, SvgSettings, SvgSun, SvgMoon, SvgCheck } from "@opal/icons";
import { cn } from "@/lib/utils";
import { ThemePreference } from "@/lib/types";

interface SettingRowProps {
  label: string;
  description?: string;
  children: React.ReactNode;
}

const SettingRow = ({ label, description, children }: SettingRowProps) => (
  <div className="nrf-settings-row">
    <div className="nrf-settings-row-label">
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
  url: string;
  isSelected: boolean;
  onClick: () => void;
}

const BackgroundThumbnail = ({
  url,
  isSelected,
  onClick,
}: BackgroundThumbnailProps) => (
  <button onClick={onClick} className="nrf-background-thumbnail group">
    <div
      className="nrf-background-thumbnail-image"
      style={{ backgroundImage: `url(${url})` }}
    />
    <div
      className={cn(
        "nrf-background-thumbnail-ring",
        isSelected
          ? "nrf-background-thumbnail-ring--selected"
          : "nrf-background-thumbnail-ring--unselected"
      )}
    />
    {isSelected && (
      <div className="nrf-background-thumbnail-check">
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
  const {
    theme,
    setTheme,
    defaultLightBackgroundUrl,
    setDefaultLightBackgroundUrl,
    defaultDarkBackgroundUrl,
    setDefaultDarkBackgroundUrl,
    useOnyxAsNewTab,
  } = useNRFPreferences();

  const toggleTheme = (newTheme: ThemePreference) => {
    setTheme(newTheme);
  };

  const updateBackgroundUrl = (url: string) => {
    if (theme === ThemePreference.LIGHT) {
      setDefaultLightBackgroundUrl(url);
    } else {
      setDefaultDarkBackgroundUrl(url);
    }
  };

  const currentBackgroundUrl =
    theme === ThemePreference.LIGHT
      ? defaultLightBackgroundUrl
      : defaultDarkBackgroundUrl;
  const backgroundImages =
    theme === ThemePreference.LIGHT
      ? lightExtensionImages
      : darkExtensionImages;

  return (
    <>
      {/* Backdrop overlay */}
      <div
        className={cn(
          "nrf-settings-overlay",
          settingsOpen
            ? "nrf-settings-overlay--open"
            : "nrf-settings-overlay--closed"
        )}
        onClick={toggleSettings}
      />

      {/* Settings panel */}
      <div
        className={cn(
          "nrf-settings-panel",
          settingsOpen
            ? "nrf-settings-panel--open"
            : "nrf-settings-panel--closed"
        )}
      >
        {/* Header */}
        <div className="nrf-settings-header">
          <div className="nrf-settings-header-content">
            <div className="nrf-settings-title-group">
              <div className="nrf-settings-icon-container">
                <SvgSettings className="w-5 h-5 stroke-text-03" />
              </div>
              <Text headingH3 text04>
                Settings
              </Text>
            </div>
            <div className="nrf-settings-actions">
              {/* Theme Toggle */}
              <IconButton
                icon={theme === ThemePreference.LIGHT ? SvgSun : SvgMoon}
                onClick={() =>
                  toggleTheme(
                    theme === ThemePreference.LIGHT
                      ? ThemePreference.DARK
                      : ThemePreference.LIGHT
                  )
                }
                tertiary
                tooltip={`Switch to ${
                  theme === ThemePreference.LIGHT
                    ? ThemePreference.DARK
                    : ThemePreference.LIGHT
                } theme`}
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

        <div className="nrf-settings-content">
          {/* General Section */}
          <section className="nrf-settings-section">
            <Text secondaryAction text03 className="nrf-settings-section-title">
              General
            </Text>
            <div className="nrf-settings-section-content">
              <SettingRow label="Use Onyx as new tab page">
                <Switch
                  checked={useOnyxAsNewTab}
                  onCheckedChange={handleUseOnyxToggle}
                />
              </SettingRow>
            </div>
          </section>

          {/* Background Section */}
          <section className="nrf-settings-section">
            <Text secondaryAction text03 className="nrf-settings-section-title">
              Background
            </Text>
            <div className="nrf-background-grid">
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
