"use client";

import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { InputHorizontal, InputVertical, Section, toast } from "@opal/layouts";
import {
  InputSingleSelect,
  InputSwitch,
  SelectButton,
  SelectCard,
  Text,
} from "@opal/components";
import { SvgCheck, SvgMonitor, SvgMoon, SvgSun } from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
import { useAppearancePreferences } from "@/lib/appearance/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { type Locale } from "@/i18n/config";
import { LanguageSelect } from "@/lib/app/components";
import { ThemePreference } from "@/lib/types";
import useScreenSize from "@/hooks/useScreenSize";
import { useSmoothStreaming } from "@/hooks/useSmoothStreaming";
import { useWideChat } from "@/providers/WideChatProvider";
import {
  CHAT_BACKGROUND_OPTIONS,
  CHAT_BACKGROUND_NONE,
} from "@/lib/constants/chatBackgrounds";
import SettingsSection from "@/views/settings/SettingsSection";

const THEME_OPTIONS = [
  {
    value: ThemePreference.SYSTEM,
    icon: SvgMonitor,
    labelKey: "appearance.colorMode.auto",
  },
  {
    value: ThemePreference.LIGHT,
    icon: SvgSun,
    labelKey: "appearance.colorMode.light",
  },
  {
    value: ThemePreference.DARK,
    icon: SvgMoon,
    labelKey: "appearance.colorMode.dark",
  },
] as const;

/**
 * The appearance preferences shown as a select, with their values. Each one
 * has `title`, `description` and one key per value under
 * `settings.appearance.<preference>` in the message catalogs.
 */
const APPEARANCE_SELECT_VALUES = {
  transcriptWidth: ["standard", "wide"],
} as const;

type AppearanceSelectPreference = keyof typeof APPEARANCE_SELECT_VALUES;
type AppearanceSelectValue<K extends AppearanceSelectPreference> =
  (typeof APPEARANCE_SELECT_VALUES)[K][number];
type AppearanceSelectOptionKey = {
  [K in AppearanceSelectPreference]: `${K}.${AppearanceSelectValue<K>}`;
}[AppearanceSelectPreference];

interface AppearanceSelectProps<K extends AppearanceSelectPreference> {
  preference: K;
  value: AppearanceSelectValue<K>;
  onValueChange: (value: AppearanceSelectValue<K>) => void;
}

/** A settings row with a select for one appearance preference. */
function AppearanceSelect<K extends AppearanceSelectPreference>({
  preference,
  value,
  onValueChange,
}: AppearanceSelectProps<K>) {
  const t = useTranslations("settings.appearance");
  const values: readonly AppearanceSelectValue<K>[] =
    APPEARANCE_SELECT_VALUES[preference];
  const titleKey: `${AppearanceSelectPreference}.title` = `${preference}.title`;
  const descriptionKey: `${AppearanceSelectPreference}.description` = `${preference}.description`;
  const title = t(titleKey);

  return (
    <InputHorizontal
      title={title}
      description={t(descriptionKey)}
      center
      withLabel
      fillInput
    >
      <InputSingleSelect
        value={value}
        onValueChange={(selected) => {
          const match = values.find((option) => option === selected);
          if (match !== undefined) onValueChange(match);
        }}
        defaultOption={values[0]}
        placeholder={title}
        aria-label={title}
        options={values.map((option) => {
          const optionKey: AppearanceSelectOptionKey = `${preference}.${option}`;
          return { value: option, title: t(optionKey) };
        })}
      />
    </InputHorizontal>
  );
}

export default function AppearanceSettings() {
  const t = useTranslations("settings");
  const tBg = useTranslations("common.chatBackgrounds");
  const { user, updatePreferences, updateUserLanguage } = useUser();
  const workspaceLanguage: Locale = useSettings().default_language;
  const { theme } = useTheme();
  const { chooseTheme, chooseChatBackground } = useAppearancePreferences();
  const { wideChat, setWideChat } = useWideChat();
  const { isMobile } = useScreenSize();
  const {
    enabled: smoothStreamingEnabled,
    setEnabled: setSmoothStreamingEnabled,
  } = useSmoothStreaming();

  const bgLabels = new Map([
    ["none", tBg("none.label")],
    ["clouds", tBg("clouds.label")],
    ["hills", tBg("hills.label")],
    ["plant", tBg("plant.label")],
    ["mountains", tBg("mountains.label")],
    ["night", tBg("night.label")],
  ]);
  return (
    <Section gap={8}>
      <SettingsSection title={t("appearance.general.title")}>
        <InputHorizontal
          title={t("appearance.colorMode.title")}
          description={t("appearance.colorMode.description")}
          center
        >
          <Section
            flexDirection="row"
            width="fit"
            height="auto"
            gap={0.25}
            data-testid="theme-preference"
          >
            {THEME_OPTIONS.map((option) => {
              const selected = theme === option.value;
              return (
                <SelectButton
                  key={option.value}
                  icon={option.icon}
                  state={selected ? "selected" : "empty"}
                  tooltip={t(option.labelKey)}
                  aria-label={t(option.labelKey)}
                  aria-pressed={selected}
                  onClick={() => {
                    void chooseTheme(option.value);
                  }}
                />
              );
            })}
          </Section>
        </InputHorizontal>

        <InputHorizontal
          title={t("language.displayLanguage.title")}
          description={t("language.displayLanguage.description")}
          center
          withLabel
          fillInput
        >
          <LanguageSelect
            aria-label={t("language.displayLanguage.title")}
            value={user?.preferences?.language ?? null}
            globalDefault={workspaceLanguage}
            onChange={(language) => {
              updateUserLanguage(language).catch(() => {
                toast.error(t("language.toasts.updateFailed"));
              });
            }}
          />
        </InputHorizontal>

        <InputVertical title={t("appearance.chatBackground.title")}>
          <Section
            flexDirection="row"
            justifyContent="start"
            height="fit"
            gap={2}
            wrap
          >
            {CHAT_BACKGROUND_OPTIONS.map((bg) => {
              const currentBackgroundId =
                user?.preferences?.chat_background ?? "none";
              const isSelected = currentBackgroundId === bg.id;
              const isNone = bg.src === CHAT_BACKGROUND_NONE;
              const label = bgLabels.get(bg.id) ?? bg.label;

              return (
                // SelectCard fills its parent, so a fit-width Section sizes
                // each tile to its thumbnail.
                <Section key={bg.id} width="fit" height="fit">
                  <SelectCard
                    padding={0}
                    rounding={2}
                    state={isSelected ? "selected" : "empty"}
                    group="group/background"
                    onClick={() => void chooseChatBackground(bg)}
                    role="button"
                    tabIndex={0}
                    title={label}
                    aria-label={t("appearance.chatBackground.optionAriaLabel", {
                      label,
                      selected: isSelected ? "true" : "false",
                    })}
                  >
                    <div className="relative overflow-hidden rounded-08 w-[5.625rem] h-[4.25rem]">
                      {isNone ? (
                        <Section className="absolute inset-0 bg-background">
                          <Text as="p" font="secondary-body" color="text-02">
                            {t("appearance.chatBackground.none")}
                          </Text>
                        </Section>
                      ) : (
                        <div
                          className="absolute inset-0 bg-cover bg-center transition-transform duration-300 group-hover/background:scale-105"
                          style={{ backgroundImage: `url(${bg.thumbnail})` }}
                        />
                      )}
                      {isSelected && (
                        <div className="absolute top-1.5 end-1.5 rounded-full bg-theme-primary-05 p-[0.1875rem]">
                          <SvgCheck className="block w-2.5 h-2.5 stroke-text-inverted-05" />
                        </div>
                      )}
                    </div>
                  </SelectCard>
                </Section>
              );
            })}
          </Section>
        </InputVertical>

        {/* Chat is always full width on mobile widths. */}
        {!isMobile && (
          <AppearanceSelect
            preference="transcriptWidth"
            value={wideChat ? "wide" : "standard"}
            onValueChange={(width) => setWideChat(width === "wide")}
          />
        )}

        <InputHorizontal
          title={t("chats.autoScroll.title")}
          description={t("chats.autoScroll.description")}
          withLabel
        >
          <InputSwitch
            checked={user?.preferences.auto_scroll}
            onCheckedChange={(checked) => {
              void updatePreferences(
                { auto_scroll: checked },
                "/api/auto-scroll"
              );
            }}
          />
        </InputHorizontal>

        <InputHorizontal
          title={t("chats.smoothStreaming.title")}
          description={t("chats.smoothStreaming.description")}
          withLabel
        >
          <InputSwitch
            checked={smoothStreamingEnabled}
            onCheckedChange={setSmoothStreamingEnabled}
          />
        </InputHorizontal>
      </SettingsSection>
    </Section>
  );
}
