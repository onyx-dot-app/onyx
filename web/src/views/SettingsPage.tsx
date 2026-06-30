"use client";

import { useRef, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Section, AttachmentItemLayout } from "@/layouts/general-layouts";
import {
  Content,
  ContentAction,
  InputHorizontal,
  InputVertical,
} from "@opal/layouts";
import { markdown } from "@opal/utils";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import {
  SvgArrowExchange,
  SvgKey,
  SvgLock,
  SvgMinusCircle,
  SvgPlusCircle,
  SvgTrash,
  SvgUnplug,
} from "@opal/icons";
import { getSourceMetadata } from "@/lib/sources";
import Card from "@/refresh-components/cards/Card";
import { InputTypeIn } from "@opal/components";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import { Switch } from "@opal/components";
import { useUser } from "@/providers/UserProvider";
import { useTheme } from "next-themes";
import { useTranslation } from "react-i18next";
import { MemoryItem, ThemePreference } from "@/lib/types";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import { toast } from "@/hooks/useToast";
import ModelSelector from "@/sections/model-selector/ModelSelector";
import { structureValue } from "@/lib/languageModels/utils";
import { deleteAllChatSessions } from "@/app/app/services/lib";
import { useAuthType, useLlmManager } from "@/lib/hooks";
import useChatSessions from "@/hooks/useChatSessions";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useFilter from "@/hooks/useFilter";
import { Button, Divider, Checkbox, Text } from "@opal/components";
import useFederatedOAuthStatus from "@/hooks/useFederatedOAuthStatus";
import useCCPairs from "@/hooks/useCCPairs";
import { ValidSources } from "@/lib/types";
import { ConnectorCredentialPairStatus } from "@/app/admin/connector/[ccPairId]/types";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import { Code, CopyButton } from "@opal/components";
import CharacterCount from "@/refresh-components/CharacterCount";
import { InputPrompt } from "@/app/app/interfaces";
import usePromptShortcuts from "@/hooks/usePromptShortcuts";
import ColorSwatch from "@/refresh-components/ColorSwatch";
import { EmptyMessageCard } from "@opal/components";
import Memories from "@/sections/settings/Memories";
import { FederatedConnectorOAuthStatus } from "@/components/chat/FederatedOAuthModal";
import {
  CHAT_BACKGROUND_OPTIONS,
  CHAT_BACKGROUND_NONE,
} from "@/lib/constants/chatBackgrounds";
import { SvgCheck } from "@opal/icons";
import { cn } from "@opal/utils";
import { Interactive } from "@opal/core";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import { useIsSearchModeAvailable } from "@/lib/settings/hooks";
import { Tooltip } from "@opal/components";
import { useCloudSubscription } from "@/hooks/useCloudSubscription";
import { useSmoothStreaming } from "@/hooks/useSmoothStreaming";
import { findModelConfigId } from "@/lib/languageModels/options";

interface PAT {
  id: number;
  name: string;
  token_display: string;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  scopes: string[] | null;
}

interface PatScopeOption {
  scope: string;
  group_label: string;
  label: string;
  description: string;
  implies: string[];
}

type AccessMode = "full" | "limited";

interface CreatedTokenState {
  id: number;
  token: string;
  name: string;
}

interface ScopeGroup {
  label: string;
  rows: PatScopeOption[];
}

interface ScopeSelectorProps {
  scopeOptions: PatScopeOption[];
  selectedScopes: string[];
  toggleScope: (scope: string) => void;
  scopesError: boolean;
  disabled: boolean;
}

// Data-driven from the /scopes payload, so new scopes need no change here.
function ScopeSelector({
  scopeOptions,
  selectedScopes,
  toggleScope,
  scopesError,
  disabled,
}: ScopeSelectorProps) {
  const { t } = useTranslation();
  const groups = useMemo(() => {
    const byLabel = new Map<string, ScopeGroup>();
    for (const option of scopeOptions) {
      const group = byLabel.get(option.group_label);
      if (group) {
        group.rows.push(option);
      } else {
        byLabel.set(option.group_label, {
          label: option.group_label,
          rows: [option],
        });
      }
    }
    return Array.from(byLabel.values());
  }, [scopeOptions]);

  if (scopesError) {
    return (
      <Text font="secondary-body" color="text-03">
        {t(
          "settings.accounts.err_could_not_load_pats",
          "Couldn't load permissions."
        )}
      </Text>
    );
  }
  if (scopeOptions.length === 0) {
    return (
      <Text font="secondary-body" color="text-03">
        {t("settings.accounts.loading_permissions", "Loading permissions...")}
      </Text>
    );
  }

  // scope -> label of a selected scope that implies it (so it's auto-included).
  const lockedBy = new Map<string, string>();
  for (const scope of selectedScopes) {
    const option = scopeOptions.find((o) => o.scope === scope);
    option?.implies.forEach((implied) => lockedBy.set(implied, option.label));
  }

  return (
    <div className="grid grid-cols-2 items-start">
      {groups.map((group) => (
        <div key={group.label} className="flex flex-col items-start gap-1">
          <Text font="main-ui-action" color="text-04">
            {group.label}
          </Text>
          {group.rows.map((option) => {
            const lockReason = lockedBy.get(option.scope);
            const locked = lockReason !== undefined;
            return (
              <div key={option.scope} className="flex items-start gap-2 pl-2">
                <Checkbox
                  checked={selectedScopes.includes(option.scope) || locked}
                  disabled={disabled || locked}
                  onCheckedChange={() => toggleScope(option.scope)}
                  aria-label={`${group.label} ${option.label}`}
                />
                <div className="flex flex-col">
                  <Text font="main-ui-body" color="text-04">
                    {locked
                      ? t("settings.accounts.scope_included_with", {
                          defaultValue: `${option.label} (included with ${lockReason})`,
                          label: option.label,
                          reason: lockReason,
                        })
                      : option.label}
                  </Text>
                  {/* Fixed 2-line slot so every row is the same height. */}
                  <div className="h-8 overflow-hidden">
                    <Text font="secondary-body" color="text-03" maxLines={2}>
                      {option.description}
                    </Text>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

interface PATModalProps {
  isCreating: boolean;
  newTokenName: string;
  setNewTokenName: (name: string) => void;
  expirationDays: string;
  setExpirationDays: (days: string) => void;
  accessMode: AccessMode;
  setAccessMode: (mode: AccessMode) => void;
  scopeOptions: PatScopeOption[];
  scopesError: boolean;
  selectedScopes: string[];
  toggleScope: (scope: string) => void;
  onClose: () => void;
  onCreate: () => void;
  createdToken: CreatedTokenState | null;
}

function PATModal({
  isCreating,
  newTokenName,
  setNewTokenName,
  expirationDays,
  setExpirationDays,
  accessMode,
  setAccessMode,
  scopeOptions,
  scopesError,
  selectedScopes,
  toggleScope,
  onClose,
  onCreate,
  createdToken,
}: PATModalProps) {
  const { t } = useTranslation();
  if (createdToken?.token) {
    return (
      <Modal open onOpenChange={(open) => !open && onClose()}>
        <Modal.Content width="sm" height="sm">
          <Modal.Header
            title={t("settings.accounts.modal_created_title", "Access Token")}
            icon={SvgKey}
            onClose={onClose}
            description={t(
              "settings.accounts.modal_created_desc",
              "Save this token before continuing. It won't be shown again."
            )}
          />
          <Modal.Body>
            <Code showCopyButton={false}>{createdToken.token}</Code>
          </Modal.Body>
          <Modal.Footer>
            <BasicModalFooter
              submit={
                <CopyButton
                  getCopyText={() => createdToken.token}
                  prominence="primary"
                >
                  {t("settings.accounts.btn_copy_token", "Copy Token")}
                </CopyButton>
              }
            />
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    );
  }

  return (
    <ConfirmationModalLayout
      icon={SvgKey}
      title={t("settings.accounts.modal_create_title", "Create Access Token")}
      description={t(
        "settings.accounts.modal_create_desc",
        "All API requests using this token will inherit your access permissions and be attributed to you as an individual."
      )}
      onClose={onClose}
      submit={
        <Button
          disabled={
            isCreating ||
            !newTokenName.trim() ||
            (accessMode === "limited" && selectedScopes.length === 0)
          }
          onClick={onCreate}
        >
          {isCreating
            ? t("settings.accounts.creating_token", "Creating Token...")
            : t("settings.accounts.create_token", "Create Token")}
        </Button>
      }
    >
      <Section gap={1}>
        <InputVertical
          title={t("settings.accounts.token_name", "Token Name")}
          withLabel
        >
          <InputTypeIn
            placeholder={t(
              "settings.accounts.token_name_placeholder",
              "Name your token"
            )}
            value={newTokenName}
            onChange={(e) => setNewTokenName(e.target.value)}
            variant={isCreating ? "disabled" : undefined}
            autoComplete="new-password"
          />
        </InputVertical>
        <InputVertical
          title={t("settings.accounts.expires_in", "Expires in")}
          subDescription={
            expirationDays === "null"
              ? undefined
              : (() => {
                  const expiryDate = new Date();
                  expiryDate.setUTCDate(
                    expiryDate.getUTCDate() + parseInt(expirationDays)
                  );
                  expiryDate.setUTCHours(23, 59, 59, 999);
                  const dateStr = expiryDate
                    .toISOString()
                    .replace("T", " ")
                    .replace(".999Z", "");
                  return t(
                    "settings.accounts.will_expire_at",
                    "This token will expire at: {{date}} UTC",
                    { date: dateStr }
                  );
                })()
          }
          withLabel
        >
          <InputSelect
            value={expirationDays}
            onValueChange={setExpirationDays}
            disabled={isCreating}
          >
            <InputSelect.Trigger
              placeholder={t(
                "settings.accounts.select_expiration",
                "Select expiration"
              )}
            />
            <InputSelect.Content>
              <InputSelect.Item value="7">
                {t("settings.accounts.days_7", "7 days")}
              </InputSelect.Item>
              <InputSelect.Item value="30">
                {t("settings.accounts.days_30", "30 days")}
              </InputSelect.Item>
              <InputSelect.Item value="365">
                {t("settings.accounts.days_365", "365 days")}
              </InputSelect.Item>
              <InputSelect.Item value="null">
                {t("settings.accounts.no_expiration", "No expiration")}
              </InputSelect.Item>
            </InputSelect.Content>
          </InputSelect>
        </InputVertical>
        <InputVertical
          title={t("settings.accounts.permissions", "Permissions")}
          subDescription={
            accessMode === "full"
              ? t(
                  "settings.accounts.permissions_full_desc",
                  "Inherits all of your permissions."
                )
              : t(
                  "settings.accounts.permissions_limited_desc",
                  "Limit this token to specific capabilities."
                )
          }
          withLabel
        >
          <InputSelect
            value={accessMode}
            onValueChange={(value) => setAccessMode(value as AccessMode)}
            disabled={isCreating}
          >
            <InputSelect.Trigger
              placeholder={t(
                "settings.accounts.select_permissions",
                "Select permissions"
              )}
            />
            <InputSelect.Content>
              <InputSelect.Item value="full">
                {t("settings.accounts.full_access", "Full access")}
              </InputSelect.Item>
              <InputSelect.Item value="limited">
                {t("settings.accounts.permissions_limited", "Limited access")}
              </InputSelect.Item>
            </InputSelect.Content>
          </InputSelect>
        </InputVertical>
        {accessMode === "limited" && (
          <ScopeSelector
            scopeOptions={scopeOptions}
            selectedScopes={selectedScopes}
            toggleScope={toggleScope}
            scopesError={scopesError}
            disabled={isCreating}
          />
        )}
      </Section>
    </ConfirmationModalLayout>
  );
}

function GeneralSettings() {
  const {
    user,
    updateUserPersonalization,
    updateUserThemePreference,
    updateUserLanguagePreference,
    updateUserChatBackground,
  } = useUser();
  const { theme, setTheme, systemTheme } = useTheme();
  const { t, i18n } = useTranslation();

  const applyBackground = useCallback(
    async (bg: (typeof CHAT_BACKGROUND_OPTIONS)[number]) => {
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
    },
    [updateUserChatBackground, setTheme, updateUserThemePreference]
  );
  const { refreshChatSessions } = useChatSessions();
  const router = useRouter();
  const pathname = usePathname();
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);

  const {
    personalizationValues,
    updatePersonalizationField,
    handleSavePersonalization,
  } = useUserPersonalization(user, updateUserPersonalization, {
    onSuccess: () =>
      toast.success(
        t(
          "settings.danger_zone.toast_update_personalization_success",
          "Personalization updated successfully"
        )
      ),
    onError: () =>
      toast.error(
        t(
          "settings.danger_zone.toast_update_personalization_failed",
          "Failed to update personalization"
        )
      ),
  });

  // Track initial values to detect changes
  const initialNameRef = useRef(personalizationValues.name);
  const initialRoleRef = useRef(personalizationValues.role);

  // Update refs when personalization values change from external source
  useEffect(() => {
    initialNameRef.current = personalizationValues.name;
    initialRoleRef.current = personalizationValues.role;
  }, [user?.personalization]);

  const handleDeleteAllChats = useCallback(async () => {
    setIsDeleting(true);
    try {
      const response = await deleteAllChatSessions();
      if (response.ok) {
        toast.success(
          t(
            "settings.danger_zone.toast_success",
            "All your chat sessions have been deleted."
          )
        );
        await refreshChatSessions();
        setShowDeleteConfirmation(false);
      } else {
        throw new Error("Failed to delete all chat sessions");
      }
    } catch (error) {
      toast.error(
        t(
          "settings.danger_zone.toast_failed",
          "Failed to delete all chat sessions"
        )
      );
    } finally {
      setIsDeleting(false);
    }
  }, [pathname, router, refreshChatSessions, t]);

  return (
    <>
      {showDeleteConfirmation && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={t("settings.danger_zone.confirm_title", "Delete All Chats")}
          onClose={() => setShowDeleteConfirmation(false)}
          submit={
            <Button
              disabled={isDeleting}
              variant="danger"
              onClick={() => {
                void handleDeleteAllChats();
              }}
            >
              {isDeleting
                ? t("settings.danger_zone.deleting", "Deleting...")
                : t("settings.danger_zone.delete_btn", "Delete")}
            </Button>
          }
        >
          <Section gap={0.5} alignItems="start">
            <Text color="text-05">
              {t(
                "settings.danger_zone.confirm_desc_1",
                "All your chat sessions and history will be permanently deleted. Deletion cannot be undone."
              )}
            </Text>
            <Text color="text-05">
              {t(
                "settings.danger_zone.confirm_desc_2",
                "Are you sure you want to delete all chats?"
              )}
            </Text>
          </Section>
        </ConfirmationModalLayout>
      )}

      <Section gap={2}>
        <Section gap={0.75}>
          <Content
            title={t("settings.profile.title", "Profile")}
            sizePreset="main-content"
            variant="section"
            width="full"
          />
          <Card>
            <InputHorizontal
              title={t("settings.profile.full_name", "Full Name")}
              description={t(
                "settings.profile.full_name_desc",
                "We'll display this name in the app."
              )}
              center
              withLabel
            >
              <InputTypeIn
                placeholder={t(
                  "settings.profile.full_name_placeholder",
                  "Your name"
                )}
                value={personalizationValues.name}
                onChange={(e) =>
                  updatePersonalizationField("name", e.target.value)
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.currentTarget.blur();
                  }
                }}
                onBlur={() => {
                  // Only save if the value has changed
                  if (personalizationValues.name !== initialNameRef.current) {
                    void handleSavePersonalization();
                    initialNameRef.current = personalizationValues.name;
                  }
                }}
              />
            </InputHorizontal>
            <InputHorizontal
              title={t("settings.profile.work_role", "Work Role")}
              description={t(
                "settings.profile.work_role_desc",
                "Share your role to better tailor responses."
              )}
              center
              withLabel
            >
              <InputTypeIn
                placeholder={t(
                  "settings.profile.work_role_placeholder",
                  "Your role"
                )}
                value={personalizationValues.role}
                onChange={(e) =>
                  updatePersonalizationField("role", e.target.value)
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.currentTarget.blur();
                  }
                }}
                onBlur={() => {
                  // Only save if the value has changed
                  if (personalizationValues.role !== initialRoleRef.current) {
                    void handleSavePersonalization();
                    initialRoleRef.current = personalizationValues.role;
                  }
                }}
              />
            </InputHorizontal>
          </Card>
        </Section>

        <Section gap={0.75}>
          <Content
            title={t("settings.appearance.title", "Appearance")}
            sizePreset="main-content"
            variant="section"
            width="full"
          />
          <Card>
            <InputHorizontal
              title={t("settings.appearance.color_mode", "Color Mode")}
              description={t(
                "settings.appearance.color_mode_desc",
                "Select your preferred color mode for the UI."
              )}
              center
              withLabel
            >
              <InputSelect
                value={theme}
                onValueChange={(value) => {
                  setTheme(value);
                  updateUserThemePreference(value as ThemePreference);
                }}
              >
                <InputSelect.Trigger />
                <InputSelect.Content>
                  <InputSelect.Item
                    value={ThemePreference.SYSTEM}
                    icon={() => (
                      <ColorSwatch
                        light={systemTheme === "light"}
                        dark={systemTheme === "dark"}
                      />
                    )}
                    description={
                      systemTheme
                        ? systemTheme.charAt(0).toUpperCase() +
                          systemTheme.slice(1)
                        : undefined
                    }
                  >
                    {t("settings.appearance.mode_auto", "Auto")}
                  </InputSelect.Item>
                  <InputSelect.Separator />
                  <InputSelect.Item
                    value={ThemePreference.LIGHT}
                    icon={() => <ColorSwatch light />}
                  >
                    {t("settings.appearance.mode_light", "Light")}
                  </InputSelect.Item>
                  <InputSelect.Item
                    value={ThemePreference.DARK}
                    icon={() => <ColorSwatch dark />}
                  >
                    {t("settings.appearance.mode_dark", "Dark")}
                  </InputSelect.Item>
                </InputSelect.Content>
              </InputSelect>
            </InputHorizontal>
            <InputHorizontal
              title={t("general.language")}
              description={t("settings.language_description")}
              center
              withLabel
            >
              <InputSelect
                value={user?.preferences?.language ?? i18n.language ?? "en"}
                onValueChange={(value) => {
                  updateUserLanguagePreference(value);
                }}
              >
                <InputSelect.Trigger />
                <InputSelect.Content>
                  <InputSelect.Item value="en">English</InputSelect.Item>
                  <InputSelect.Item value="es">Español</InputSelect.Item>
                  <InputSelect.Item value="fr">Français</InputSelect.Item>
                  <InputSelect.Item value="pt">Português</InputSelect.Item>
                  <InputSelect.Item value="de">Deutsch</InputSelect.Item>
                </InputSelect.Content>
              </InputSelect>
            </InputHorizontal>
            <InputVertical
              title={t(
                "settings.appearance.chat_background",
                "Chat Background"
              )}
            >
              <div className="flex flex-wrap gap-2">
                {CHAT_BACKGROUND_OPTIONS.map((bg) => {
                  const currentBackgroundId =
                    user?.preferences?.chat_background ?? "none";
                  const isSelected = currentBackgroundId === bg.id;
                  const isNone = bg.src === CHAT_BACKGROUND_NONE;

                  return (
                    <button
                      key={bg.id}
                      onClick={() => applyBackground(bg)}
                      className="relative overflow-hidden rounded-lg transition-all w-[90px] h-[68px] cursor-pointer border-none p-0 bg-transparent group"
                      title={bg.label}
                      aria-label={`${bg.label} background${
                        isSelected ? " (selected)" : ""
                      }`}
                    >
                      {isNone ? (
                        <div className="absolute inset-0 bg-background flex items-center justify-center">
                          <span className="text-xs text-text-02">
                            {t("settings.appearance.bg_none", "None")}
                          </span>
                        </div>
                      ) : (
                        <div
                          className="absolute inset-0 bg-cover bg-center transition-transform duration-300 group-hover:scale-105"
                          style={{ backgroundImage: `url(${bg.thumbnail})` }}
                        />
                      )}
                      <div
                        className={cn(
                          "absolute inset-0 transition-all rounded-lg",
                          isSelected
                            ? "ring-2 ring-inset ring-theme-primary-05"
                            : "ring-1 ring-inset ring-border-02 group-hover:ring-border-03"
                        )}
                      />
                      {isSelected && (
                        <div className="absolute top-1.5 right-1.5 w-4 h-4 rounded-full bg-theme-primary-05 flex items-center justify-center">
                          <SvgCheck className="w-2.5 h-2.5 stroke-text-inverted-05" />
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            </InputVertical>
          </Card>
        </Section>

        <Divider paddingParallel="fit" paddingPerpendicular="fit" />

        <Section gap={0.75}>
          <Content
            title={t("settings.danger_zone.title", "Danger Zone")}
            sizePreset="main-content"
            variant="section"
            width="full"
          />
          <Card>
            <InputHorizontal
              title={t(
                "settings.danger_zone.delete_all_chats",
                "Delete All Chats"
              )}
              description={t(
                "settings.danger_zone.delete_all_chats_desc",
                "Permanently delete all your chat sessions."
              )}
              center
            >
              <Button
                variant="danger"
                prominence="secondary"
                onClick={() => setShowDeleteConfirmation(true)}
                icon={SvgTrash}
                interaction={showDeleteConfirmation ? "hover" : "rest"}
              >
                {t("settings.danger_zone.delete_all_chats", "Delete All Chats")}
              </Button>
            </InputHorizontal>
          </Card>
        </Section>
      </Section>
    </>
  );
}

interface LocalShortcut extends InputPrompt {
  isNew: boolean;
}

function PromptShortcuts() {
  const { promptShortcuts, isLoading, error, refresh } = usePromptShortcuts();
  const [shortcuts, setShortcuts] = useState<LocalShortcut[]>([]);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const { t } = useTranslation();

  // Initialize shortcuts when input prompts are loaded
  useEffect(() => {
    if (isLoading || error) return;

    // Convert InputPrompt[] to LocalShortcut[] with isNew: false for existing items
    // Sort by id to maintain stable ordering when editing
    const existingShortcuts: LocalShortcut[] = promptShortcuts
      .map((shortcut) => ({
        ...shortcut,
        isNew: false,
      }))
      .sort((a, b) => a.id - b.id);

    // Always ensure there's at least one empty row
    setShortcuts([
      ...existingShortcuts,
      {
        id: Date.now(),
        prompt: "",
        content: "",
        active: true,
        is_public: false,
        isNew: true,
      },
    ]);
    setIsInitialLoad(false);
  }, [promptShortcuts, isLoading, error]);

  // Show error popup if fetch fails
  useEffect(() => {
    if (!error) return;
    toast.error(
      t("settings.shortcuts.toast_load_failed", "Failed to load shortcuts")
    );
  }, [error, t]);

  const handleUpdateShortcut = useCallback(
    (index: number, field: "prompt" | "content", value: string) => {
      setShortcuts((prev) => {
        const next = prev.map((shortcut, i) =>
          i === index ? { ...shortcut, [field]: value } : shortcut
        );

        const isEmptyNew = (s: LocalShortcut) =>
          s.isNew && !s.prompt.trim() && !s.content.trim();

        const emptyCount = next.filter(isEmptyNew).length;

        if (emptyCount === 0) {
          return [
            ...next,
            {
              id: Date.now(),
              prompt: "",
              content: "",
              active: true,
              is_public: false,
              isNew: true,
            },
          ];
        }

        if (emptyCount > 1) {
          const userRow = next[index];
          const userRowEmpty = userRow !== undefined && isEmptyNew(userRow);
          let keepIndex = -1;
          if (userRowEmpty) {
            keepIndex = index;
          } else {
            for (let i = next.length - 1; i >= 0; i--) {
              const row = next[i];
              if (row !== undefined && isEmptyNew(row)) {
                keepIndex = i;
                break;
              }
            }
          }
          return next.filter((s, i) => !isEmptyNew(s) || i === keepIndex);
        }

        return next;
      });
    },
    []
  );

  const handleRemoveShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut) return;

      // If it's a new shortcut, just remove from state
      if (shortcut.isNew) {
        setShortcuts((prev) => prev.filter((_, i) => i !== index));
        return;
      }

      // Otherwise, delete from backend
      try {
        const response = await fetch(`/api/input_prompt/${shortcut.id}`, {
          method: "DELETE",
        });

        if (response.ok) {
          setShortcuts((prev) => prev.filter((_, i) => i !== index));
          await refresh();
          toast.success(
            t("settings.shortcuts.toast_deleted", "Shortcut deleted")
          );
        } else {
          throw new Error("Failed to delete shortcut");
        }
      } catch (error) {
        toast.error(
          t(
            "settings.shortcuts.toast_delete_failed",
            "Failed to delete shortcut"
          )
        );
      }
    },
    [shortcuts, refresh, t]
  );

  const handleSaveShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut || !shortcut.prompt.trim() || !shortcut.content.trim()) {
        toast.error(
          t(
            "settings.shortcuts.err_both_required",
            "Both shortcut and expansion are required"
          )
        );
        return;
      }

      try {
        if (shortcut.isNew) {
          // Create new shortcut
          const response = await fetch("/api/input_prompt", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: shortcut.prompt,
              content: shortcut.content,
              active: true,
              is_public: false,
            }),
          });

          if (response.ok) {
            await refresh();
            toast.success(
              t("settings.shortcuts.toast_created", "Shortcut created")
            );
          } else {
            throw new Error("Failed to create shortcut");
          }
        } else {
          // Update existing shortcut
          const response = await fetch(`/api/input_prompt/${shortcut.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: shortcut.prompt,
              content: shortcut.content,
              active: true,
              is_public: false,
            }),
          });

          if (response.ok) {
            await refresh();
            toast.success(
              t("settings.shortcuts.toast_updated", "Shortcut updated")
            );
          } else {
            throw new Error("Failed to update shortcut");
          }
        }
      } catch (error) {
        toast.error(
          t("settings.shortcuts.toast_save_failed", "Failed to save shortcut")
        );
      }
    },
    [shortcuts, refresh, t]
  );

  const handleBlurShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut) return;

      const hasPrompt = shortcut.prompt.trim();
      const hasContent = shortcut.content.trim();

      // Both fields are filled - save/update the shortcut
      if (hasPrompt && hasContent) {
        await handleSaveShortcut(index);
      }
      // For existing shortcuts with incomplete fields, error state will be shown in UI
      // User must use the delete button to remove them
    },
    [shortcuts, handleSaveShortcut]
  );

  return (
    <>
      {shortcuts.length > 0 && (
        <Section gap={0.75}>
          {shortcuts.map((shortcut, index) => {
            const isEmpty = !shortcut.prompt.trim() && !shortcut.content.trim();
            const isExisting = !shortcut.isNew;
            const hasPrompt = shortcut.prompt.trim();
            const hasContent = shortcut.content.trim();

            // Show error for existing shortcuts with incomplete fields
            // (either one field empty or both fields empty)
            const showPromptError = isExisting && !hasPrompt;
            const showContentError = isExisting && !hasContent;

            return (
              <div
                key={shortcut.id}
                className="w-full grid grid-cols-[1fr_min-content] gap-x-1 gap-y-1"
              >
                <InputTypeIn
                  prefixText="/"
                  placeholder={t(
                    "settings.shortcuts.summarize_placeholder",
                    "Summarize"
                  )}
                  value={shortcut.prompt}
                  onChange={(e) =>
                    handleUpdateShortcut(index, "prompt", e.target.value)
                  }
                  onBlur={
                    shortcut.is_public
                      ? undefined
                      : () => void handleBlurShortcut(index)
                  }
                  variant={
                    shortcut.is_public
                      ? "readOnly"
                      : showPromptError
                        ? "error"
                        : undefined
                  }
                />
                <Section>
                  <Button
                    disabled={(shortcut.isNew && isEmpty) || shortcut.is_public}
                    icon={SvgMinusCircle}
                    onClick={() => void handleRemoveShortcut(index)}
                    prominence="tertiary"
                    aria-label={t(
                      "settings.shortcuts.remove_aria",
                      "Remove shortcut"
                    )}
                    tooltip={
                      shortcut.is_public
                        ? t(
                            "settings.shortcuts.cannot_delete_public",
                            "Cannot delete public prompt-shortcuts."
                          )
                        : undefined
                    }
                  />
                </Section>
                <InputTextArea
                  placeholder={t(
                    "settings.shortcuts.content_placeholder",
                    "Provide a concise 1ÔÇô2 sentence summary of the following:"
                  )}
                  value={shortcut.content}
                  onChange={(e) =>
                    handleUpdateShortcut(index, "content", e.target.value)
                  }
                  onBlur={
                    shortcut.is_public
                      ? undefined
                      : () => void handleBlurShortcut(index)
                  }
                  variant={
                    shortcut.is_public
                      ? "readOnly"
                      : showContentError
                        ? "error"
                        : undefined
                  }
                  rows={3}
                />
                <div />
              </div>
            );
          })}
        </Section>
      )}
    </>
  );
}

function ChatPreferencesSettings() {
  const {
    user,
    updateUserPersonalization,
    updateUserAutoScroll,
    updateUserShortcuts,
    updateUserPasteAsTile,
    updateUserDefaultModel,
    updateUserDefaultAppMode,
    updateUserVoiceSettings,
  } = useUser();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const searchUiEnabled = useIsSearchModeAvailable();
  const llmManager = useLlmManager();
  const {
    enabled: smoothStreamingEnabled,
    setEnabled: setSmoothStreamingEnabled,
  } = useSmoothStreaming();
  const { t } = useTranslation();

  const {
    personalizationValues,
    toggleUseMemories,
    toggleEnableMemoryTool,
    updateUserPreferences,
    handleSavePersonalization,
  } = useUserPersonalization(user, updateUserPersonalization, {
    onSuccess: () =>
      toast.success(t("settings.chats.toast_prefs_saved", "Preferences saved")),
    onError: () =>
      toast.error(
        t("settings.chats.toast_prefs_failed", "Failed to save preferences")
      ),
  });
  const [draftVoicePlaybackSpeed, setDraftVoicePlaybackSpeed] = useState(
    user?.preferences.voice_playback_speed ?? 1
  );

  useEffect(() => {
    setDraftVoicePlaybackSpeed(user?.preferences.voice_playback_speed ?? 1);
  }, [user?.preferences.voice_playback_speed]);

  const saveVoiceSettings = useCallback(
    async (settings: {
      auto_send?: boolean;
      auto_playback?: boolean;
      playback_speed?: number;
    }) => {
      try {
        await updateUserVoiceSettings(settings);
        toast.success(
          t("settings.chats.toast_prefs_saved", "Preferences saved")
        );
      } catch {
        toast.error(
          t("settings.chats.toast_prefs_failed", "Failed to save preferences")
        );
      }
    },
    [updateUserVoiceSettings, t]
  );

  const commitVoicePlaybackSpeed = useCallback(() => {
    const currentSpeed = user?.preferences.voice_playback_speed ?? 1;
    if (Math.abs(currentSpeed - draftVoicePlaybackSpeed) < 0.001) {
      return;
    }
    void saveVoiceSettings({
      playback_speed: draftVoicePlaybackSpeed,
    });
  }, [
    draftVoicePlaybackSpeed,
    saveVoiceSettings,
    user?.preferences.voice_playback_speed,
  ]);

  // Wrapper to save memories and return success/failure
  const handleSaveMemories = useCallback(
    async (newMemories: MemoryItem[]): Promise<boolean> => {
      const result = await handleSavePersonalization(
        { memories: newMemories },
        true
      );
      return !!result;
    },
    [handleSavePersonalization]
  );

  return (
    <Section gap={2}>
      <Section gap={0.75}>
        <Content
          title={t("settings.chats.title", "Chats")}
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        <Card>
          <InputHorizontal
            title={t("settings.chats.default_model", "Default Model")}
            description={t(
              "settings.chats.default_model_desc",
              "This model will be used by Onyx by default in your chats."
            )}
            withLabel
          >
            <ModelSelector
              value={
                user?.preferences?.default_model
                  ? findModelConfigId(
                      llmManager.llmProviders,
                      llmManager.currentLlm.provider,
                      llmManager.currentLlm.modelName
                    )
                  : null
              }
              onChange={(opt) => {
                if (opt.modelConfigurationId === null) {
                  void updateUserDefaultModel(null);
                } else {
                  llmManager.updateCurrentLlm({
                    name: opt.name,
                    provider: opt.provider,
                    modelName: opt.modelName,
                  });
                  void updateUserDefaultModel(
                    structureValue(opt.name, opt.provider, opt.modelName)
                  );
                }
              }}
              temperatureManager={llmManager}
              includeGlobalDefault
              side="bottom"
            />
          </InputHorizontal>

          <InputHorizontal
            title={t("settings.chats.auto_scroll", "Chat Auto-scroll")}
            description={t(
              "settings.chats.auto_scroll_desc",
              "Automatically scroll to new content as chat generates response."
            )}
            withLabel
          >
            <Switch
              checked={user?.preferences.auto_scroll}
              onCheckedChange={(checked) => {
                updateUserAutoScroll(checked);
              }}
            />
          </InputHorizontal>

          <InputHorizontal
            title={t("settings.chats.smooth_streaming", "Smooth Streaming")}
            description={t(
              "settings.chats.smooth_streaming_desc",
              "Animate streamed responses character-by-character. Disable to render chunks as they arrive."
            )}
            withLabel
          >
            <Switch
              checked={smoothStreamingEnabled}
              onCheckedChange={setSmoothStreamingEnabled}
            />
          </InputHorizontal>

          <InputHorizontal
            title={t("settings.chats.collapse_pastes", "Collapse Large Pastes")}
            description={t(
              "settings.chats.collapse_pastes_desc",
              "When pasting text longer than 3 lines or 200 characters, collapse it into a compact tile instead of inserting it inline. Click the tile to view or edit the full text."
            )}
            withLabel
          >
            <Switch
              checked={user?.preferences?.paste_as_tile ?? false}
              onCheckedChange={(checked) => {
                updateUserPasteAsTile(checked);
              }}
            />
          </InputHorizontal>

          {businessTier && (
            <Tooltip
              tooltip={
                searchUiEnabled
                  ? undefined
                  : t(
                      "settings.chats.search_ui_disabled_tooltip",
                      "Search UI is disabled and can only be enabled by an admin."
                    )
              }
              side="top"
            >
              <InputHorizontal
                title={t("settings.chats.default_app_mode", "Default App Mode")}
                description={t(
                  "settings.chats.default_app_mode_desc",
                  "Choose whether new sessions start in Search or Chat mode."
                )}
                center
                disabled={!searchUiEnabled}
                withLabel
              >
                <InputSelect
                  value={user?.preferences.default_app_mode ?? "CHAT"}
                  onValueChange={(value) => {
                    void updateUserDefaultAppMode(value as "CHAT" | "SEARCH");
                  }}
                  disabled={!searchUiEnabled}
                >
                  <InputSelect.Trigger />
                  <InputSelect.Content>
                    <InputSelect.Item value="CHAT">
                      {t("settings.chats.mode_chat", "Chat")}
                    </InputSelect.Item>
                    <InputSelect.Item value="SEARCH">
                      {t("settings.chats.mode_search", "Search")}
                    </InputSelect.Item>
                  </InputSelect.Content>
                </InputSelect>
              </InputHorizontal>
            </Tooltip>
          )}
        </Card>
      </Section>

      <Section gap={0.75}>
        <InputVertical
          title={t(
            "settings.chats.personal_prefs_title",
            "Personal Preferences"
          )}
          description={t(
            "settings.chats.personal_prefs_desc",
            "Provide your custom preferences in natural language."
          )}
          withLabel
        >
          <InputTextArea
            placeholder={t(
              "settings.chats.personal_prefs_placeholder",
              "Describe how you want the system to behave and the tone it should use."
            )}
            value={personalizationValues.user_preferences}
            onChange={(e) => updateUserPreferences(e.target.value)}
            onBlur={() => void handleSavePersonalization()}
            rows={4}
            maxRows={10}
            autoResize
            maxLength={500}
          />
          <CharacterCount
            value={personalizationValues.user_preferences || ""}
            limit={500}
          />
        </InputVertical>
        <Content
          title={t("settings.chats.memory_title", "Memory")}
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        <Card>
          <InputHorizontal
            title={t(
              "settings.chats.ref_memories",
              "Reference Stored Memories"
            )}
            description={t(
              "settings.chats.ref_memories_desc",
              "Let Onyx reference stored memories in chats."
            )}
            withLabel
          >
            <Switch
              checked={personalizationValues.use_memories}
              onCheckedChange={(checked) => {
                toggleUseMemories(checked);
                void handleSavePersonalization({ use_memories: checked });
              }}
            />
          </InputHorizontal>
          <InputHorizontal
            title={t("settings.chats.update_memories", "Update Memories")}
            description={t(
              "settings.chats.update_memories_desc",
              "Let Onyx generate and update stored memories."
            )}
            withLabel
          >
            <Switch
              checked={personalizationValues.enable_memory_tool}
              onCheckedChange={(checked) => {
                toggleEnableMemoryTool(checked);
                void handleSavePersonalization({
                  enable_memory_tool: checked,
                });
              }}
            />
          </InputHorizontal>

          {(personalizationValues.use_memories ||
            personalizationValues.enable_memory_tool ||
            personalizationValues.memories.length > 0) && (
            <Memories
              memories={personalizationValues.memories}
              onSaveMemories={handleSaveMemories}
            />
          )}
        </Card>
      </Section>

      <Section gap={0.75}>
        <Content
          title={t("settings.chats.prompt_shortcuts_title", "Prompt Shortcuts")}
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        <Card>
          <InputHorizontal
            title={t(
              "settings.chats.use_prompt_shortcuts",
              "Use Prompt Shortcuts"
            )}
            description={t(
              "settings.chats.use_prompt_shortcuts_desc",
              "Enable shortcuts to quickly insert common prompts."
            )}
            withLabel
          >
            <Switch
              checked={user?.preferences?.shortcut_enabled}
              onCheckedChange={(checked) => {
                updateUserShortcuts(checked);
              }}
            />
          </InputHorizontal>

          {user?.preferences?.shortcut_enabled && <PromptShortcuts />}
        </Card>
      </Section>

      <Section gap={0.75}>
        <Content
          title={t("settings.chats.voice_title", "Voice")}
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        <Card>
          <InputHorizontal
            title={t("settings.chats.voice_auto_send", "Auto-Send on Pause")}
            description={t(
              "settings.chats.voice_auto_send_desc",
              "Automatically send voice input when you stop speaking."
            )}
            withLabel
          >
            <Switch
              checked={user?.preferences.voice_auto_send ?? false}
              onCheckedChange={(checked) => {
                void saveVoiceSettings({ auto_send: checked });
              }}
            />
          </InputHorizontal>

          <InputHorizontal
            title={t("settings.chats.voice_auto_playback", "Auto-Playback")}
            description={t(
              "settings.chats.voice_auto_playback_desc",
              "Automatically play voice responses."
            )}
            withLabel
          >
            <Switch
              checked={user?.preferences.voice_auto_playback ?? false}
              onCheckedChange={(checked) => {
                void saveVoiceSettings({ auto_playback: checked });
              }}
            />
          </InputHorizontal>

          <InputHorizontal
            title={t("settings.chats.voice_playback_speed", "Playback Speed")}
            description={t(
              "settings.chats.voice_playback_speed_desc",
              "Adjust the speed of voice playback."
            )}
            withLabel
          >
            <div className="flex items-center gap-3">
              <input
                type="range"
                min="0.5"
                max="2"
                step="0.1"
                value={draftVoicePlaybackSpeed}
                onChange={(e) => {
                  setDraftVoicePlaybackSpeed(parseFloat(e.target.value));
                }}
                onMouseUp={commitVoicePlaybackSpeed}
                onTouchEnd={commitVoicePlaybackSpeed}
                onKeyUp={(e) => {
                  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                    commitVoicePlaybackSpeed();
                  }
                }}
                className="w-24 h-2 rounded-lg appearance-none cursor-pointer bg-background-neutral-02"
              />
              <span className="text-sm text-text-02 w-10">
                {draftVoicePlaybackSpeed.toFixed(1)}x
              </span>
            </div>
          </InputHorizontal>
        </Card>
      </Section>
    </Section>
  );
}

function AccountsAccessSettings() {
  const { user, authTypeMetadata } = useUser();
  const authType = useAuthType();
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const { t } = useTranslation();

  const passwordValidationSchema = Yup.object().shape({
    currentPassword: Yup.string().required(
      t(
        "settings.accounts.current_password_required",
        "Current password is required"
      )
    ),
    newPassword: Yup.string()
      .min(
        authTypeMetadata.passwordMinLength,
        t("settings.accounts.new_password_min_length", {
          defaultValue: `Password must be at least ${authTypeMetadata.passwordMinLength} characters`,
          count: authTypeMetadata.passwordMinLength,
        })
      )
      .required(
        t("settings.accounts.new_password_required", "New password is required")
      ),
    confirmPassword: Yup.string()
      .oneOf(
        [Yup.ref("newPassword")],
        t("settings.accounts.passwords_do_not_match", "Passwords do not match")
      )
      .required(
        t(
          "settings.accounts.confirm_password_required",
          "Please confirm your new password"
        )
      ),
  });

  // PAT state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [newTokenName, setNewTokenName] = useState("");
  const [expirationDays, setExpirationDays] = useState<string>("30");
  const [accessMode, setAccessMode] = useState<AccessMode>("full");
  const [selectedScopes, setSelectedScopes] = useState<string[]>([]);
  const [newlyCreatedToken, setNewlyCreatedToken] =
    useState<CreatedTokenState | null>(null);
  const [tokenToDelete, setTokenToDelete] = useState<PAT | null>(null);

  const canCreateTokens = useCloudSubscription();

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = authType !== null;

  // Fetch PATs with SWR
  const {
    data: pats = [],
    mutate,
    error,
    isLoading,
  } = useSWR<PAT[]>(
    showTokensSection ? SWR_KEYS.userPats : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: true,
      dedupingInterval: 2000,
      fallbackData: [],
    }
  );

  const { data: scopeOptions = [], error: scopeOptionsError } = useSWR<
    PatScopeOption[]
  >(
    showTokensSection && canCreateTokens ? SWR_KEYS.userPatScopes : null,
    errorHandlingFetcher,
    { fallbackData: [] }
  );

  const scopeLabels = useMemo(
    () =>
      new Map(
        scopeOptions.map((o) => [
          o.scope,
          `${o.label} ${o.group_label.toLowerCase()}`,
        ])
      ),
    [scopeOptions]
  );

  const toggleScope = useCallback((scope: string) => {
    setSelectedScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]
    );
  }, []);

  // Use filter hook for searching tokens
  const {
    query,
    setQuery,
    filtered: filteredPats,
  } = useFilter(pats, (pat) => `${pat.name} ${pat.token_display}`);

  // Show error popup if SWR fetch fails
  useEffect(() => {
    if (error) {
      toast.error(
        t("settings.accounts.toast_load_failed", "Failed to load tokens")
      );
    }
  }, [error, t]);

  useEffect(() => {
    if (scopeOptionsError) {
      toast.error(
        t(
          "settings.accounts.toast_load_scopes_failed",
          "Failed to load permission options"
        )
      );
    }
  }, [scopeOptionsError, t]);

  const createPAT = useCallback(async () => {
    if (!newTokenName.trim()) {
      toast.error(
        t("settings.accounts.err_name_required", "Token name is required")
      );
      return;
    }

    setIsCreating(true);
    try {
      const response = await fetch("/api/user/pats", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newTokenName,
          expiration_days:
            expirationDays === "null" ? null : parseInt(expirationDays),
          scopes: accessMode === "limited" ? selectedScopes : null,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        // Store the newly created token - modal will switch to display view
        setNewlyCreatedToken({
          id: data.id,
          token: data.token,
          name: newTokenName,
        });
        toast.success(
          t(
            "settings.accounts.toast_create_success",
            "Token created successfully"
          )
        );
        // Revalidate the token list
        await mutate();
      } else {
        const errorData = await response.json();
        toast.error(
          errorData.detail ||
            t("settings.accounts.toast_create_failed", "Failed to create token")
        );
      }
    } catch (error) {
      toast.error(
        t(
          "settings.accounts.toast_create_network_error",
          "Network error creating token"
        )
      );
    } finally {
      setIsCreating(false);
    }
  }, [newTokenName, expirationDays, accessMode, selectedScopes, mutate, t]);

  const deletePAT = useCallback(
    async (patId: number) => {
      try {
        const response = await fetch(`/api/user/pats/${patId}`, {
          method: "DELETE",
        });

        if (response.ok) {
          // Clear the newly created token if it's the one being deleted
          if (newlyCreatedToken?.id === patId) {
            setNewlyCreatedToken(null);
          }
          await mutate();
          toast.success(
            t(
              "settings.accounts.toast_delete_success",
              "Token deleted successfully"
            )
          );
          setTokenToDelete(null);
        } else {
          toast.error(
            t("settings.accounts.toast_delete_failed", "Failed to delete token")
          );
        }
      } catch (error) {
        toast.error(
          t(
            "settings.accounts.toast_delete_network_error",
            "Network error deleting token"
          )
        );
      }
    },
    [newlyCreatedToken, mutate, t]
  );

  const handleChangePassword = useCallback(
    async (values: {
      currentPassword: string;
      newPassword: string;
      confirmPassword: string;
    }) => {
      try {
        const response = await fetch("/api/password/change-password", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            old_password: values.currentPassword,
            new_password: values.newPassword,
          }),
        });

        if (response.ok) {
          toast.success(
            t(
              "settings.accounts.toast_success",
              "Password updated successfully"
            )
          );
          setShowPasswordModal(false);
        } else {
          const errorData = await response.json();
          toast.error(
            errorData.detail ||
              t("settings.accounts.toast_failed", "Failed to change password")
          );
        }
      } catch (error) {
        toast.error(
          t(
            "settings.accounts.toast_error_occurred",
            "An error occurred while changing the password"
          )
        );
      }
    },
    [t]
  );

  return (
    <>
      {showCreateModal && (
        <PATModal
          isCreating={isCreating}
          newTokenName={newTokenName}
          setNewTokenName={setNewTokenName}
          expirationDays={expirationDays}
          setExpirationDays={setExpirationDays}
          accessMode={accessMode}
          setAccessMode={setAccessMode}
          scopeOptions={scopeOptions}
          scopesError={Boolean(scopeOptionsError)}
          selectedScopes={selectedScopes}
          toggleScope={toggleScope}
          onClose={() => {
            setShowCreateModal(false);
            setNewTokenName("");
            setExpirationDays("30");
            setAccessMode("full");
            setSelectedScopes([]);
            setNewlyCreatedToken(null);
          }}
          onCreate={createPAT}
          createdToken={newlyCreatedToken}
        />
      )}

      {tokenToDelete && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={t(
            "settings.accounts.modal_revoke_title",
            "Revoke Access Token"
          )}
          onClose={() => setTokenToDelete(null)}
          submit={
            <Button
              variant="danger"
              onClick={() => deletePAT(tokenToDelete.id)}
            >
              {t("settings.accounts.btn_revoke", "Revoke")}
            </Button>
          }
        >
          <Section gap={0.5} alignItems="start">
            <Text color="text-05">
              {t("settings.accounts.revoke_desc_1", {
                defaultValue: `Any application using the token ${tokenToDelete.name} (${tokenToDelete.token_display}) will lose access to Onyx. This action cannot be undone.`,
                name: tokenToDelete.name,
                display: tokenToDelete.token_display,
              })}
            </Text>
            <Text color="text-05">
              {t(
                "settings.accounts.revoke_desc_2",
                "Are you sure you want to revoke this token?"
              )}
            </Text>
          </Section>
        </ConfirmationModalLayout>
      )}

      {showPasswordModal && (
        <Formik
          initialValues={{
            currentPassword: "",
            newPassword: "",
            confirmPassword: "",
          }}
          validationSchema={passwordValidationSchema}
          validateOnChange={true}
          validateOnBlur={true}
          onSubmit={() => undefined}
        >
          {({
            values,
            handleChange,
            handleBlur,
            isSubmitting,
            dirty,
            isValid,
            errors,
            touched,
            setSubmitting,
          }) => (
            <Form>
              <ConfirmationModalLayout
                icon={SvgLock}
                title={t(
                  "settings.accounts.change_password",
                  "Change Password"
                )}
                submit={
                  <Button
                    disabled={isSubmitting || !dirty || !isValid}
                    onClick={async () => {
                      setSubmitting(true);
                      try {
                        await handleChangePassword(values);
                      } finally {
                        setSubmitting(false);
                      }
                    }}
                  >
                    {isSubmitting
                      ? t("settings.accounts.updating", "Updating...")
                      : t("settings.accounts.btn_update", "Update")}
                  </Button>
                }
                onClose={() => {
                  setShowPasswordModal(false);
                }}
              >
                <Section gap={1}>
                  <Section gap={0.25} alignItems="start">
                    <InputVertical
                      withLabel="currentPassword"
                      title={t(
                        "settings.accounts.current_password",
                        "Current Password"
                      )}
                    >
                      <PasswordInputTypeIn
                        name="currentPassword"
                        value={values.currentPassword}
                        onChange={handleChange}
                        onBlur={handleBlur}
                        error={
                          touched.currentPassword && !!errors.currentPassword
                        }
                      />
                    </InputVertical>
                  </Section>
                  <Section gap={0.25} alignItems="start">
                    <InputVertical
                      withLabel="newPassword"
                      title={t(
                        "settings.accounts.new_password",
                        "New Password"
                      )}
                    >
                      <PasswordInputTypeIn
                        name="newPassword"
                        value={values.newPassword}
                        onChange={handleChange}
                        onBlur={handleBlur}
                        error={touched.newPassword && !!errors.newPassword}
                      />
                    </InputVertical>
                  </Section>
                  <Section gap={0.25} alignItems="start">
                    <InputVertical
                      withLabel="confirmPassword"
                      title={t(
                        "settings.accounts.confirm_new_password",
                        "Confirm New Password"
                      )}
                    >
                      <PasswordInputTypeIn
                        name="confirmPassword"
                        value={values.confirmPassword}
                        onChange={handleChange}
                        onBlur={handleBlur}
                        error={
                          touched.confirmPassword && !!errors.confirmPassword
                        }
                      />
                    </InputVertical>
                  </Section>
                </Section>
              </ConfirmationModalLayout>
            </Form>
          )}
        </Formik>
      )}

      <Section gap={2}>
        <Section gap={0.75}>
          <Content
            title={t("settings.accounts.title", "Accounts")}
            sizePreset="main-content"
            variant="section"
            width="full"
          />
          <Card>
            <InputHorizontal
              title={t("settings.accounts.email", "Email")}
              description={t(
                "settings.accounts.email_desc",
                "Your account email address."
              )}
              center
            >
              <Text color="text-05">{user?.email ?? "anonymous"}</Text>
            </InputHorizontal>

            {showPasswordSection && (
              <InputHorizontal
                title={t("settings.accounts.password", "Password")}
                description={t(
                  "settings.accounts.password_desc",
                  "Update your account password."
                )}
                center
              >
                <Button
                  prominence="secondary"
                  icon={SvgLock}
                  onClick={() => setShowPasswordModal(true)}
                  interaction={showPasswordModal ? "hover" : "rest"}
                >
                  {t("settings.accounts.change_password", "Change Password")}
                </Button>
              </InputHorizontal>
            )}
          </Card>
        </Section>

        {showTokensSection && (
          <Section gap={0.75}>
            <Content
              title={t("settings.accounts.access_tokens", "Access Tokens")}
              sizePreset="main-content"
              variant="section"
              width="full"
            />
            {canCreateTokens ? (
              <Card padding={0.25}>
                <Section gap={0}>
                  <Section flexDirection="row" padding={0.25} gap={0.5}>
                    {pats.length === 0 ? (
                      <Section padding={0.5} alignItems="start">
                        <Text font="secondary-body" color="text-03">
                          {isLoading
                            ? t(
                                "settings.accounts.loading_tokens",
                                "Loading tokens..."
                              )
                            : t(
                                "settings.accounts.no_tokens",
                                "No access tokens created."
                              )}
                        </Text>
                      </Section>
                    ) : (
                      <InputTypeIn
                        placeholder={t(
                          "settings.accounts.search_placeholder",
                          "Search..."
                        )}
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        searchIcon
                        variant="internal"
                      />
                    )}
                    <div className="shrink-0">
                      <Button
                        rightIcon={SvgPlusCircle}
                        prominence="internal"
                        interaction={showCreateModal ? "active" : "rest"}
                        onClick={() => setShowCreateModal(true)}
                      >
                        {t(
                          "settings.accounts.new_access_token",
                          "New Access Token"
                        )}
                      </Button>
                    </div>
                  </Section>

                  <Section gap={0.25}>
                    {filteredPats.map((pat) => {
                      const now = new Date();
                      const createdDate = new Date(pat.created_at);
                      const daysSinceCreation = Math.floor(
                        (now.getTime() - createdDate.getTime()) /
                          (1000 * 60 * 60 * 24)
                      );

                      let expiryText = t(
                        "settings.accounts.never_expires",
                        "Never expires"
                      );
                      if (pat.expires_at) {
                        const expiresDate = new Date(pat.expires_at);
                        const daysUntilExpiry = Math.ceil(
                          (expiresDate.getTime() - now.getTime()) /
                            (1000 * 60 * 60 * 24)
                        );
                        expiryText =
                          daysUntilExpiry === 1
                            ? t(
                                "settings.accounts.expires_in_day",
                                "Expires in 1 day"
                              )
                            : t("settings.accounts.expires_in_days", {
                                defaultValue: `Expires in ${daysUntilExpiry} days`,
                                days: daysUntilExpiry,
                              });
                      }

                      const scopeText =
                        pat.scopes === null
                          ? t("settings.accounts.full_access", "Full access")
                          : pat.scopes
                              .map((scope) => scopeLabels.get(scope) ?? scope)
                              .join(", ");

                      const createdText =
                        daysSinceCreation === 0
                          ? t(
                              "settings.accounts.created_today",
                              "Created today"
                            )
                          : daysSinceCreation === 1
                            ? t(
                                "settings.accounts.created_day_ago",
                                "Created 1 day ago"
                              )
                            : t("settings.accounts.created_days_ago", {
                                defaultValue: `Created ${daysSinceCreation} days ago`,
                                days: daysSinceCreation,
                              });

                      const middleText = `${createdText} - ${expiryText} - ${scopeText}`;

                      return (
                        <Interactive.Container
                          key={pat.id}
                          size="fit"
                          width="full"
                        >
                          <div className="w-full bg-background-tint-01">
                            <AttachmentItemLayout
                              icon={SvgKey}
                              title={pat.name}
                              description={pat.token_display}
                              middleText={middleText}
                              rightChildren={
                                <Button
                                  icon={SvgTrash}
                                  onClick={() => setTokenToDelete(pat)}
                                  prominence="tertiary"
                                  size="sm"
                                  aria-label={
                                    t(
                                      "settings.accounts.modal_revoke_title",
                                      "Revoke Access Token"
                                    ) +
                                    " " +
                                    pat.name
                                  }
                                />
                              }
                            />
                          </div>
                        </Interactive.Container>
                      );
                    })}
                  </Section>
                </Section>
              </Card>
            ) : (
              <Card>
                <Section flexDirection="row" justifyContent="between">
                  <Text font="secondary-body" color="text-03">
                    {t(
                      "settings.accounts.paid_subscription_required",
                      "Access tokens require an active paid subscription."
                    )}
                  </Text>
                  <Button prominence="secondary" href="/admin/billing">
                    {t("settings.accounts.btn_upgrade_plan", "Upgrade Plan")}
                  </Button>
                </Section>
              </Card>
            )}
          </Section>
        )}
      </Section>
    </>
  );
}

interface IndexedConnectorCardProps {
  source: ValidSources;
  isActive: boolean;
}

function IndexedConnectorCard({ source, isActive }: IndexedConnectorCardProps) {
  const sourceMetadata = getSourceMetadata(source);
  const { t } = useTranslation();

  return (
    <Card>
      <Content
        icon={sourceMetadata.icon}
        title={sourceMetadata.displayName}
        description={
          isActive
            ? t("settings.connectors.connected", "Connected")
            : t("settings.connectors.paused", "Paused")
        }
        sizePreset="main-content"
        variant="section"
      />
    </Card>
  );
}

interface FederatedConnectorCardProps {
  connector: FederatedConnectorOAuthStatus;
  onDisconnectSuccess: () => void;
}

function FederatedConnectorCard({
  connector,
  onDisconnectSuccess,
}: FederatedConnectorCardProps) {
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [showDisconnectConfirmation, setShowDisconnectConfirmation] =
    useState(false);
  const sourceMetadata = getSourceMetadata(connector.source as ValidSources);
  const { t } = useTranslation();

  const handleDisconnect = useCallback(async () => {
    setIsDisconnecting(true);
    try {
      const response = await fetch(
        `/api/federated/${connector.federated_connector_id}/oauth`,
        { method: "DELETE" }
      );

      if (response.ok) {
        toast.success(
          t(
            "settings.connectors.toast_disconnect_success",
            "Disconnected successfully"
          )
        );
        setShowDisconnectConfirmation(false);
        onDisconnectSuccess();
      } else {
        throw new Error("Failed to disconnect");
      }
    } catch (error) {
      toast.error(
        t("settings.connectors.toast_disconnect_failed", "Failed to disconnect")
      );
    } finally {
      setIsDisconnecting(false);
    }
  }, [connector.federated_connector_id, onDisconnectSuccess, t]);

  return (
    <>
      {showDisconnectConfirmation && (
        <ConfirmationModalLayout
          icon={SvgUnplug}
          title={markdown(
            t("settings.connectors.modal_disconnect_title", {
              defaultValue: `Disconnect *${sourceMetadata.displayName}*`,
              name: sourceMetadata.displayName,
            })
          )}
          onClose={() => setShowDisconnectConfirmation(false)}
          submit={
            <Button
              disabled={isDisconnecting}
              variant="danger"
              onClick={() => void handleDisconnect()}
            >
              {isDisconnecting
                ? t("settings.connectors.btn_disconnecting", "Disconnecting...")
                : t("settings.connectors.btn_disconnect", "Disconnect")}
            </Button>
          }
        >
          <Section gap={0.5} alignItems="start">
            <Text color="text-05">
              {t("settings.connectors.disconnect_desc_1", {
                defaultValue: `Onyx will no longer be able to access or search content from your ${sourceMetadata.displayName} account.`,
                name: sourceMetadata.displayName,
              })}
            </Text>
            <Text color="text-05">
              {t("settings.connectors.disconnect_desc_2", {
                defaultValue: `You can still continue existing sessions referencing ${sourceMetadata.displayName} content.`,
                name: sourceMetadata.displayName,
              })}
            </Text>
          </Section>
        </ConfirmationModalLayout>
      )}

      <Card padding={0.5}>
        <ContentAction
          icon={sourceMetadata.icon}
          title={sourceMetadata.displayName}
          description={
            connector.has_oauth_token
              ? t("settings.connectors.connected", "Connected")
              : t("settings.connectors.not_connected", "Not connected")
          }
          sizePreset="main-content"
          variant="section"
          padding="sm"
          rightChildren={
            connector.has_oauth_token ? (
              <Button
                disabled={isDisconnecting}
                icon={SvgUnplug}
                prominence="tertiary"
                size="sm"
                onClick={() => setShowDisconnectConfirmation(true)}
              />
            ) : connector.authorize_url ? (
              <Button
                prominence="internal"
                href={connector.authorize_url}
                target="_blank"
                rightIcon={SvgArrowExchange}
              >
                {t("settings.connectors.btn_connect", "Connect")}
              </Button>
            ) : undefined
          }
        />
      </Card>
    </>
  );
}

function ConnectorsSettings() {
  const {
    connectors: federatedConnectors,
    refetch: refetchFederatedConnectors,
  } = useFederatedOAuthStatus();
  const { ccPairs } = useCCPairs();
  const { t } = useTranslation();

  const ACTIVE_STATUSES: ConnectorCredentialPairStatus[] = [
    ConnectorCredentialPairStatus.ACTIVE,
    ConnectorCredentialPairStatus.SCHEDULED,
    ConnectorCredentialPairStatus.INITIAL_INDEXING,
  ];

  // Group indexed connectors by source
  const groupedConnectors = ccPairs.reduce(
    (acc, ccPair) => {
      if (!acc[ccPair.source]) {
        acc[ccPair.source] = {
          source: ccPair.source,
          hasActiveConnector: false,
        };
      }
      if (ACTIVE_STATUSES.includes(ccPair.status)) {
        acc[ccPair.source]!.hasActiveConnector = true;
      }
      return acc;
    },
    {} as Record<
      string,
      {
        source: ValidSources;
        hasActiveConnector: boolean;
      }
    >
  );

  const hasConnectors =
    Object.keys(groupedConnectors).length > 0 || federatedConnectors.length > 0;

  return (
    <Section gap={2}>
      <Section gap={0.75} justifyContent="start">
        <Content
          title={t("settings.connectors.title", "Connectors")}
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        {hasConnectors ? (
          <>
            {/* Indexed Connectors */}
            {Object.values(groupedConnectors).map((connector) => (
              <IndexedConnectorCard
                key={connector.source}
                source={connector.source}
                isActive={connector.hasActiveConnector}
              />
            ))}

            {/* Federated Connectors */}
            {federatedConnectors.map((connector) => (
              <FederatedConnectorCard
                key={connector.federated_connector_id}
                connector={connector}
                onDisconnectSuccess={() => refetchFederatedConnectors?.()}
              />
            ))}
          </>
        ) : (
          <EmptyMessageCard
            sizePreset="main-ui"
            title={t(
              "settings.connectors.no_connectors_title",
              "No connectors set up for your organization."
            )}
          />
        )}
      </Section>
    </Section>
  );
}

export {
  GeneralSettings,
  ChatPreferencesSettings,
  AccountsAccessSettings,
  ConnectorsSettings,
};
