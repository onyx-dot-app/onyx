"use client";

import { useRef, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Section, AttachmentItemLayout } from "@/layouts/general-layouts";
import {
  Content,
  ContentAction,
  InputHorizontal,
  InputVertical,
  toast,
} from "@opal/layouts";
import { copyText, markdown } from "@opal/utils";
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
import {
  Card,
  InputTextArea,
  InputTypeIn,
  PasswordInputTypeIn,
} from "@opal/components";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Switch } from "@opal/components";
import { useUser } from "@/providers/UserProvider";
import { useTheme } from "next-themes";
import { MemoryItem, Permission, ThemePreference } from "@/lib/types";
import {
  DEFAULT_LOCALE,
  LOCALE_ENDONYMS,
  SUPPORTED_LOCALES,
  type Locale,
} from "@/i18n/config";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import ModelSelector from "@/sections/model-selector/ModelSelector";
import { structureValue } from "@/lib/languageModels/utils";
import { deleteAllChatSessions } from "@/app/app/services/lib";
import { useLlmManager } from "@/lib/hooks";
import { useIsMultiTenant } from "@/lib/auth/hooks";
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
import { ConfirmationModalLayout } from "@opal/layouts";
import { BasicModalFooter, Modal } from "@opal/components";
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
import { useIsSearchModeAvailable, useSettings } from "@/lib/settings/hooks";
import {
  ALL_REASONING_STOPS,
  PaneSlider,
  REASONING_STOP_LABELS,
  UNSET_REASONING_STOP,
  reasoningStopIndex,
} from "@/sections/model-selector/setting-controls";
import { LLM_GATEWAY_MIN_TIER, tierAtLeast } from "@/lib/tiers";
import { Tooltip } from "@opal/components";
import { useCloudSubscription } from "@/hooks/useCloudSubscription";
import { useSmoothStreaming } from "@/hooks/useSmoothStreaming";
import { hasPermission } from "@/lib/permissions";
import { findModelConfigId } from "@/lib/languageModels/options";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { DOCS_BASE_URL } from "@/lib/constants";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";

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
  min_tier: Tier;
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
  const t = useTranslations("settings");
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
        {t("apiKeys.scopeSelector.loadError")}
      </Text>
    );
  }
  if (scopeOptions.length === 0) {
    return (
      <Text font="secondary-body" color="text-03">
        {t("apiKeys.scopeSelector.loading")}
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
                    {lockReason !== undefined
                      ? t("apiKeys.scopeSelector.includedWith", {
                          label: option.label,
                          lockReason,
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
  const t = useTranslations("settings");

  if (createdToken?.token) {
    return (
      <Modal open onOpenChange={(open) => !open && onClose()}>
        <Modal.Content width="sm" height="sm">
          <Modal.Header
            title={t("apiKeys.tokenCreatedModal.title")}
            icon={SvgKey}
            onClose={onClose}
            description={t("apiKeys.tokenCreatedModal.description")}
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
                  {t("apiKeys.tokenCreatedModal.copyButton")}
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
      title={t("apiKeys.createModal.title")}
      description={t("apiKeys.createModal.description")}
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
            ? t("apiKeys.createModal.submit.creating")
            : t("apiKeys.createModal.submit.create")}
        </Button>
      }
    >
      <Section gap={4}>
        <InputVertical title={t("apiKeys.createModal.name.title")} withLabel>
          <InputTypeIn
            placeholder={t("apiKeys.createModal.name.placeholder")}
            value={newTokenName}
            onChange={(e) => setNewTokenName(e.target.value)}
            variant={isCreating ? "disabled" : undefined}
            autoComplete="new-password"
          />
        </InputVertical>
        <InputVertical
          title={t("apiKeys.createModal.expiration.title")}
          subDescription={
            expirationDays === "null"
              ? undefined
              : (() => {
                  const expiryDate = new Date();
                  expiryDate.setUTCDate(
                    expiryDate.getUTCDate() + parseInt(expirationDays)
                  );
                  expiryDate.setUTCHours(23, 59, 59, 999);
                  const formattedDate = expiryDate
                    .toISOString()
                    .replace("T", " ")
                    .replace(".999Z", " UTC");
                  return t("apiKeys.createModal.expiration.expiresAtNote", {
                    date: formattedDate,
                  });
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
              placeholder={t("apiKeys.createModal.expiration.placeholder")}
            />
            <InputSelect.Content>
              <InputSelect.Item value="7">
                {t("apiKeys.createModal.expiration.days7")}
              </InputSelect.Item>
              <InputSelect.Item value="30">
                {t("apiKeys.createModal.expiration.days30")}
              </InputSelect.Item>
              <InputSelect.Item value="365">
                {t("apiKeys.createModal.expiration.days365")}
              </InputSelect.Item>
              <InputSelect.Item value="null">
                {t("apiKeys.createModal.expiration.noExpiration")}
              </InputSelect.Item>
            </InputSelect.Content>
          </InputSelect>
        </InputVertical>
        <InputVertical
          title={t("apiKeys.createModal.permissions.title")}
          subDescription={
            accessMode === "full"
              ? t("apiKeys.createModal.permissions.fullAccessNote")
              : t("apiKeys.createModal.permissions.limitedAccessNote")
          }
          withLabel
        >
          <InputSelect
            value={accessMode}
            onValueChange={(value) => setAccessMode(value as AccessMode)}
            disabled={isCreating}
          >
            <InputSelect.Trigger
              placeholder={t("apiKeys.createModal.permissions.placeholder")}
            />
            <InputSelect.Content>
              <InputSelect.Item value="full">
                {t("apiKeys.createModal.permissions.fullAccessOption")}
              </InputSelect.Item>
              <InputSelect.Item value="limited">
                {t("apiKeys.createModal.permissions.limitedAccessOption")}
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

interface UsePATCreationOptions {
  defaultName?: string;
  defaultAccessMode?: AccessMode;
  defaultScopes?: string[];
  onCreateSuccess?: () => Promise<void> | void;
}

function usePATCreation({
  defaultName = "",
  defaultAccessMode = "full",
  defaultScopes = [],
  onCreateSuccess,
}: UsePATCreationOptions = {}) {
  const t = useTranslations("settings");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [newTokenName, setNewTokenName] = useState(defaultName);
  const [expirationDays, setExpirationDays] = useState<string>("30");
  const [accessMode, setAccessMode] = useState<AccessMode>(defaultAccessMode);
  const [selectedScopes, setSelectedScopes] = useState<string[]>(defaultScopes);
  const [newlyCreatedToken, setNewlyCreatedToken] =
    useState<CreatedTokenState | null>(null);

  const toggleScope = useCallback((scope: string) => {
    setSelectedScopes((previous) =>
      previous.includes(scope)
        ? previous.filter((selected) => selected !== scope)
        : [...previous, scope]
    );
  }, []);

  const reset = useCallback(() => {
    setNewTokenName(defaultName);
    setExpirationDays("30");
    setAccessMode(defaultAccessMode);
    setSelectedScopes(defaultScopes);
    setNewlyCreatedToken(null);
  }, [defaultAccessMode, defaultName, defaultScopes]);

  const openTokenModal = useCallback(() => {
    reset();
    setShowCreateModal(true);
  }, [reset]);

  const closeTokenModal = useCallback(() => {
    setShowCreateModal(false);
    reset();
  }, [reset]);

  const createPAT = useCallback(async () => {
    if (!newTokenName.trim()) {
      toast.error(t("apiKeys.toasts.nameRequired"));
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
        setNewlyCreatedToken({
          id: data.id,
          token: data.token,
          name: newTokenName,
        });
        toast.success(t("apiKeys.toasts.created"));
        await onCreateSuccess?.();
      } else {
        const errorData = await response.json();
        toast.error(errorData.detail || t("apiKeys.toasts.createFailed"));
      }
    } catch (error) {
      console.error("Failed to create access token", error);
      toast.error(t("apiKeys.toasts.createNetworkError"));
    } finally {
      setIsCreating(false);
    }
  }, [
    accessMode,
    expirationDays,
    newTokenName,
    onCreateSuccess,
    selectedScopes,
    t,
  ]);

  return {
    showCreateModal,
    isCreating,
    newTokenName,
    setNewTokenName,
    expirationDays,
    setExpirationDays,
    accessMode,
    setAccessMode,
    selectedScopes,
    toggleScope,
    newlyCreatedToken,
    openTokenModal,
    closeTokenModal,
    createPAT,
  };
}

function GeneralSettings() {
  const t = useTranslations("settings");
  const {
    user,
    updateUserPersonalization,
    updateUserThemePreference,
    updateUserChatBackground,
    updateUserLanguage,
  } = useUser();
  const { theme, setTheme, systemTheme } = useTheme();
  const currentLanguage = user?.preferences?.language ?? DEFAULT_LOCALE;

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
    onSuccess: () => toast.success(t("profile.toasts.updated")),
    onError: () => toast.error(t("profile.toasts.updateFailed")),
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
        toast.success(t("dangerZone.deleteAllChats.toasts.deleted"));
        await refreshChatSessions();
        setShowDeleteConfirmation(false);
      } else {
        throw new Error("Failed to delete all chat sessions");
      }
    } catch (error) {
      toast.error(t("dangerZone.deleteAllChats.toasts.deleteFailed"));
    } finally {
      setIsDeleting(false);
    }
  }, [pathname, router, refreshChatSessions, t]);

  return (
    <>
      {showDeleteConfirmation && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={t("dangerZone.deleteAllChats.confirm.title")}
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
                ? t("dangerZone.deleteAllChats.confirm.deleting")
                : t("dangerZone.deleteAllChats.confirm.submit")}
            </Button>
          }
        >
          <Section gap={2} alignItems="start">
            <Text color="text-05">
              {t("dangerZone.deleteAllChats.confirm.description")}
            </Text>
            <Text color="text-05">
              {t("dangerZone.deleteAllChats.confirm.question")}
            </Text>
          </Section>
        </ConfirmationModalLayout>
      )}

      <Section gap={8}>
        <Section gap={3}>
          <Content
            title={t("profile.title")}
            sizePreset="main-content"
            variant="section"
            width="full"
          />
          <Card border="solid" rounding={4}>
            <Section alignItems="start" height="fit">
              <InputHorizontal
                title={t("profile.fullName.title")}
                description={t("profile.fullName.description")}
                center
                withLabel
                responsive
              >
                <InputTypeIn
                  placeholder={t("profile.fullName.placeholder")}
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
                title={t("profile.workRole.title")}
                description={t("profile.workRole.description")}
                center
                withLabel
                responsive
              >
                <InputTypeIn
                  placeholder={t("profile.workRole.placeholder")}
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
            </Section>
          </Card>
        </Section>

        <Section gap={3}>
          <Content
            title={t("appearance.title")}
            sizePreset="main-content"
            variant="section"
            width="full"
          />
          <Card border="solid" rounding={4}>
            <Section alignItems="start" height="fit">
              <InputHorizontal
                title={t("appearance.colorMode.title")}
                description={t("appearance.colorMode.description")}
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
                        systemTheme === "light"
                          ? t("appearance.colorMode.light")
                          : systemTheme === "dark"
                            ? t("appearance.colorMode.dark")
                            : undefined
                      }
                    >
                      {t("appearance.colorMode.auto")}
                    </InputSelect.Item>
                    <InputSelect.Separator />
                    <InputSelect.Item
                      value={ThemePreference.LIGHT}
                      icon={() => <ColorSwatch light />}
                    >
                      {t("appearance.colorMode.light")}
                    </InputSelect.Item>
                    <InputSelect.Item
                      value={ThemePreference.DARK}
                      icon={() => <ColorSwatch dark />}
                    >
                      {t("appearance.colorMode.dark")}
                    </InputSelect.Item>
                  </InputSelect.Content>
                </InputSelect>
              </InputHorizontal>
              <InputHorizontal
                title={t("appearance.language.title")}
                description={t("appearance.language.description")}
                center
                withLabel
              >
                <InputSelect
                  value={currentLanguage}
                  onValueChange={(value) => {
                    // SAFETY: the items below only carry SUPPORTED_LOCALES
                    // values, so the select can't emit anything else.
                    updateUserLanguage(value as Locale).catch(() => {
                      toast.error(t("appearance.language.updateFailed"));
                    });
                  }}
                >
                  <InputSelect.Trigger />
                  <InputSelect.Content>
                    {SUPPORTED_LOCALES.map((locale) => (
                      <InputSelect.Item key={locale} value={locale}>
                        {LOCALE_ENDONYMS[locale]}
                      </InputSelect.Item>
                    ))}
                  </InputSelect.Content>
                </InputSelect>
              </InputHorizontal>
              <InputVertical title={t("appearance.chatBackground.title")}>
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
                        aria-label={t(
                          "appearance.chatBackground.optionAriaLabel",
                          {
                            label: bg.label,
                            selected: isSelected ? "true" : "false",
                          }
                        )}
                      >
                        {isNone ? (
                          <div className="absolute inset-0 bg-background flex items-center justify-center">
                            <span className="text-xs text-text-02">
                              {t("appearance.chatBackground.none")}
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
            </Section>
          </Card>
        </Section>

        <Divider paddingParallel={0} paddingPerpendicular={0} />

        <Section gap={3}>
          <Content
            title={t("dangerZone.title")}
            sizePreset="main-content"
            variant="section"
            width="full"
          />
          <Card border="solid" rounding={4}>
            <Section alignItems="start" height="fit">
              <InputHorizontal
                title={t("dangerZone.deleteAllChats.title")}
                description={t("dangerZone.deleteAllChats.description")}
                center
              >
                <Button
                  variant="danger"
                  prominence="secondary"
                  onClick={() => setShowDeleteConfirmation(true)}
                  icon={SvgTrash}
                  interaction={showDeleteConfirmation ? "hover" : "rest"}
                >
                  {t("dangerZone.deleteAllChats.button")}
                </Button>
              </InputHorizontal>
            </Section>
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
  const t = useTranslations("settings");
  const { promptShortcuts, isLoading, error, refresh } = usePromptShortcuts();
  const [shortcuts, setShortcuts] = useState<LocalShortcut[]>([]);
  const [isInitialLoad, setIsInitialLoad] = useState(true);

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
    toast.error(t("promptShortcuts.toasts.loadFailed"));
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
          toast.success(t("promptShortcuts.toasts.deleted"));
        } else {
          throw new Error("Failed to delete shortcut");
        }
      } catch (error) {
        toast.error(t("promptShortcuts.toasts.deleteFailed"));
      }
    },
    [shortcuts, refresh, t]
  );

  const handleSaveShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut || !shortcut.prompt.trim() || !shortcut.content.trim()) {
        toast.error(t("promptShortcuts.toasts.bothRequired"));
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
            toast.success(t("promptShortcuts.toasts.created"));
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
            toast.success(t("promptShortcuts.toasts.updated"));
          } else {
            throw new Error("Failed to update shortcut");
          }
        }
      } catch (error) {
        toast.error(t("promptShortcuts.toasts.saveFailed"));
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
        <Section gap={3}>
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
                  placeholder={t("promptShortcuts.row.promptPlaceholder")}
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
                    aria-label={t("promptShortcuts.row.removeAriaLabel")}
                    tooltip={
                      shortcut.is_public
                        ? t("promptShortcuts.row.publicTooltip")
                        : undefined
                    }
                  />
                </Section>
                <InputTextArea
                  placeholder={t("promptShortcuts.row.contentPlaceholder")}
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
  const t = useTranslations("settings");
  const {
    user,
    updateUserPersonalization,
    updateUserAutoScroll,
    updateUserShortcuts,
    updateUserPasteAsTile,
    updateUserDefaultModel,
    updateUserDefaultAppMode,
    updateUserVoiceSettings,
    updateUserTemperatureDefault,
    updateUserReasoningEffortDefault,
  } = useUser();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const searchUiEnabled = useIsSearchModeAvailable();
  const llmManager = useLlmManager();
  const {
    enabled: smoothStreamingEnabled,
    setEnabled: setSmoothStreamingEnabled,
  } = useSmoothStreaming();

  const {
    personalizationValues,
    toggleUseMemories,
    toggleEnableMemoryTool,
    updateUserPreferences,
    handleSavePersonalization,
  } = useUserPersonalization(user, updateUserPersonalization, {
    onSuccess: () => toast.success(t("chats.toasts.saved")),
    onError: () => toast.error(t("chats.toasts.saveFailed")),
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
        toast.success(t("chats.toasts.saved"));
      } catch {
        toast.error(t("chats.toasts.saveFailed"));
      }
    },
    [updateUserVoiceSettings, t]
  );

  const settings = useSettings();
  const userTemperatureDefault = user?.preferences.temperature_default ?? null;
  const userEffortDefault = user?.preferences.reasoning_effort_default ?? null;
  // 0 mirrors the backend GEN_AI_TEMPERATURE fallback an untouched chat
  // actually runs with, so the parked slider never overstates the default.
  const [draftTemperature, setDraftTemperature] = useState(
    userTemperatureDefault ?? 0
  );
  const [draftEffortStop, setDraftEffortStop] = useState(() => {
    const stop = reasoningStopIndex(userEffortDefault);
    return stop >= 0 ? stop : UNSET_REASONING_STOP;
  });

  useEffect(() => {
    if (userTemperatureDefault != null) {
      setDraftTemperature(userTemperatureDefault);
    }
  }, [userTemperatureDefault]);
  useEffect(() => {
    const stop = reasoningStopIndex(userEffortDefault);
    if (stop >= 0) setDraftEffortStop(stop);
  }, [userEffortDefault]);

  const saveTemperatureDefault = useCallback(
    async (value: number): Promise<void> => {
      try {
        await updateUserTemperatureDefault(value);
        toast.success("Preferences saved");
      } catch {
        toast.error("Failed to save preferences");
      }
    },
    [updateUserTemperatureDefault]
  );

  const saveEffortDefault = useCallback(
    async (effortStop: number): Promise<void> => {
      try {
        await updateUserReasoningEffortDefault(
          ALL_REASONING_STOPS[effortStop] ?? null
        );
        toast.success("Preferences saved");
      } catch {
        toast.error("Failed to save preferences");
      }
    },
    [updateUserReasoningEffortDefault]
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
    <Section gap={8}>
      <Section gap={3}>
        <Content
          title={t("chats.title")}
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        <Card border="solid" rounding={4}>
          <Section alignItems="start" height="fit">
            <InputHorizontal
              title={t("chats.defaultModel.title")}
              description={t("chats.defaultModel.description")}
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
                      modelConfigurationId: opt.modelConfigurationId,
                    });
                    void updateUserDefaultModel(
                      structureValue(
                        opt.name,
                        opt.provider,
                        opt.modelName,
                        opt.modelConfigurationId
                      )
                    );
                  }
                }}
                temperatureManager={llmManager}
                includeGlobalDefault
                side="bottom"
              />
            </InputHorizontal>

            {(user?.preferences?.temperature_override_enabled ?? true) && (
              <InputHorizontal
                title={t("chats.defaultTemperature.title")}
                description={t("chats.defaultTemperature.description")}
                withLabel
              >
                <Section flexDirection="row" width="fit" height="auto" gap={3}>
                  <Section width={8} height="auto">
                    <PaneSlider
                      compact
                      value={draftTemperature}
                      min={0}
                      max={2}
                      step={0.1}
                      onValueChange={setDraftTemperature}
                      onValueCommit={(value) => {
                        void saveTemperatureDefault(value);
                      }}
                    />
                  </Section>
                  <Section width={4} height="auto" alignItems="end">
                    <Text font="secondary-mono" color="text-04" nowrap>
                      {draftTemperature.toFixed(1)}
                    </Text>
                  </Section>
                </Section>
              </InputHorizontal>
            )}

            {!settings.isLoading &&
              (settings.reasoning_override_enabled ?? true) && (
                <InputHorizontal
                  title={t("chats.defaultReasoningLevel.title")}
                  description={t("chats.defaultReasoningLevel.description")}
                  withLabel
                >
                  <Section
                    flexDirection="row"
                    width="fit"
                    height="auto"
                    gap={3}
                  >
                    <Section width={8} height="auto">
                      <PaneSlider
                        compact
                        value={draftEffortStop}
                        min={0}
                        max={ALL_REASONING_STOPS.length - 1}
                        step={1}
                        onValueChange={setDraftEffortStop}
                        onValueCommit={(value) => {
                          void saveEffortDefault(value);
                        }}
                      />
                    </Section>
                    <Section width={4} height="auto" alignItems="end">
                      <Text font="secondary-mono" color="text-04" nowrap>
                        {
                          REASONING_STOP_LABELS[
                            ALL_REASONING_STOPS[draftEffortStop] ?? "medium"
                          ]
                        }
                      </Text>
                    </Section>
                  </Section>
                </InputHorizontal>
              )}

            <InputHorizontal
              title={t("chats.autoScroll.title")}
              description={t("chats.autoScroll.description")}
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
              title={t("chats.smoothStreaming.title")}
              description={t("chats.smoothStreaming.description")}
              withLabel
            >
              <Switch
                checked={smoothStreamingEnabled}
                onCheckedChange={setSmoothStreamingEnabled}
              />
            </InputHorizontal>

            <InputHorizontal
              title={t("chats.collapseLargePastes.title")}
              description={t("chats.collapseLargePastes.description")}
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
                    : t("chats.defaultAppMode.disabledTooltip")
                }
                side="top"
              >
                <InputHorizontal
                  title={t("chats.defaultAppMode.title")}
                  description={t("chats.defaultAppMode.description")}
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
                        {t("chats.defaultAppMode.chatOption")}
                      </InputSelect.Item>
                      <InputSelect.Item value="SEARCH">
                        {t("chats.defaultAppMode.searchOption")}
                      </InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelect>
                </InputHorizontal>
              </Tooltip>
            )}
          </Section>
        </Card>
      </Section>

      <Section gap={3}>
        <InputVertical
          title={t("personalPreferences.title")}
          description={t("personalPreferences.description")}
          withLabel
        >
          <InputTextArea
            placeholder={t("personalPreferences.placeholder")}
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
          title={t("memory.title")}
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        <Card border="solid" rounding={4}>
          <Section alignItems="start" height="fit">
            <InputHorizontal
              title={t("memory.referenceStoredMemories.title")}
              description={t("memory.referenceStoredMemories.description")}
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
              title={t("memory.updateMemories.title")}
              description={t("memory.updateMemories.description")}
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
          </Section>
        </Card>
      </Section>

      <Section gap={3}>
        <Content
          title={t("promptShortcuts.title")}
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        <Card border="solid" rounding={4}>
          <Section alignItems="start" height="fit">
            <InputHorizontal
              title={t("promptShortcuts.toggle.title")}
              description={t("promptShortcuts.toggle.description")}
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
          </Section>
        </Card>
      </Section>

      <Section gap={3}>
        <Content
          title={t("voice.title")}
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        <Card border="solid" rounding={4}>
          <Section alignItems="start" height="fit">
            <InputHorizontal
              title={t("voice.autoSend.title")}
              description={t("voice.autoSend.description")}
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
              title={t("voice.autoPlayback.title")}
              description={t("voice.autoPlayback.description")}
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
              title={t("voice.playbackSpeed.title")}
              description={t("voice.playbackSpeed.description")}
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
          </Section>
        </Card>
      </Section>
    </Section>
  );
}

interface GatewayAccessSectionProps {
  canCreateToken: boolean;
  onCreateToken: () => void;
}

interface GatewayCopyValueButtonProps {
  value: string;
}

function GatewayCopyValueButton({ value }: GatewayCopyValueButtonProps) {
  const t = useTranslations("settings");
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await copyText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t("gateway.copyButton.copyError"));
    }
  }

  return (
    <Button
      prominence="secondary"
      size="sm"
      onClick={handleCopy}
      rightIcon={copied ? SvgCheck : undefined}
      tooltip={
        copied ? t("gateway.copyButton.copied") : t("gateway.copyButton.copy")
      }
    >
      {value}
    </Button>
  );
}

function GatewayAccessSection({
  canCreateToken,
  onCreateToken,
}: GatewayAccessSectionProps) {
  const t = useTranslations("settings");
  const gatewayTier = useTierAtLeast(LLM_GATEWAY_MIN_TIER);
  const { llmProviders } = useLLMProviders();
  const [gatewayUrl, setGatewayUrl] = useState("");

  useEffect(() => {
    setGatewayUrl(`${window.location.origin}/api/gateway/v1`);
  }, []);

  const providerGroups = useMemo(
    () =>
      (llmProviders ?? [])
        .map((provider) => ({
          id: provider.id,
          name: provider.name || provider.provider_display_name,
          models: provider.model_configurations
            .filter((model) => model.is_visible)
            .sort((first, second) => {
              if (
                first.is_recommended_default !== second.is_recommended_default
              ) {
                return first.is_recommended_default ? -1 : 1;
              }

              return first.effectiveDisplayName.localeCompare(
                second.effectiveDisplayName
              );
            })
            .map((model) => ({
              id: `${provider.id}/${model.name}`,
              name: model.effectiveDisplayName,
            })),
        }))
        .filter((provider) => provider.models.length > 0)
        .sort((first, second) => first.name.localeCompare(second.name)),
    [llmProviders]
  );

  const availableModelCount = providerGroups.reduce(
    (count, provider) => count + provider.models.length,
    0
  );

  if (!gatewayTier || availableModelCount === 0) {
    return null;
  }

  const gatewayAddress = gatewayUrl || "/api/gateway/v1";

  return (
    <Section gap={3}>
      <ContentAction
        title={t("gateway.title")}
        description={t("gateway.description")}
        sizePreset="main-content"
        variant="section"
        width="full"
        center
        rightChildren={
          <Button
            prominence="tertiary"
            href={`${DOCS_BASE_URL}/developers/guides/llm_gateway`}
            target="_blank"
            size="sm"
          >
            {t("gateway.guideButton")}
          </Button>
        }
      />
      <Card border="solid" rounding={4} padding={3}>
        <Section alignItems="start" height="fit" gap={3}>
          <InputHorizontal
            title={t("gateway.url.title")}
            description={t("gateway.url.description")}
            center
          >
            <GatewayCopyValueButton value={gatewayAddress} />
          </InputHorizontal>

          <Divider />

          <Section gap={2} alignItems="start">
            <Content
              title={t("gateway.models.title")}
              description={t("gateway.models.description", {
                count: availableModelCount,
              })}
              sizePreset="main-ui"
              variant="section"
            />

            <Section gap={2} alignItems="start">
              {providerGroups.map((provider) => (
                <SimpleCollapsible key={provider.id} defaultOpen={false}>
                  <SimpleCollapsible.Header
                    title={provider.name}
                    description={t("gateway.provider.modelsAvailable", {
                      count: provider.models.length,
                    })}
                    sizePreset="main-ui"
                  />
                  <SimpleCollapsible.Content>
                    <Section gap={2} alignItems="start">
                      {provider.models.map((model) => (
                        <Section
                          key={model.id}
                          flexDirection="row"
                          justifyContent="between"
                          alignItems="center"
                          height="fit"
                          gap={2}
                        >
                          <Text font="main-ui-body" color="text-04">
                            {model.name}
                          </Text>
                          <GatewayCopyValueButton value={model.id} />
                        </Section>
                      ))}
                    </Section>
                  </SimpleCollapsible.Content>
                </SimpleCollapsible>
              ))}
            </Section>
          </Section>

          <Divider />

          <InputHorizontal
            title={t("gateway.accessToken.title")}
            description={t("gateway.accessToken.description")}
            center
          >
            <Button
              prominence="secondary"
              icon={SvgKey}
              disabled={!canCreateToken}
              onClick={onCreateToken}
            >
              {t("gateway.accessToken.button")}
            </Button>
          </InputHorizontal>
        </Section>
      </Card>
    </Section>
  );
}

function LLMGatewaySettings() {
  const t = useTranslations("settings");
  const { permissions } = useUser();
  // Same gate as the Access Tokens section: this is a second PAT-minting path.
  const canCreatePAT = hasPermission(
    permissions,
    Permission.CREATE_USER_API_KEYS
  );
  const canCreateTokens = useCloudSubscription();
  const tokenCreation = usePATCreation({
    defaultName: t("gateway.title"),
    defaultAccessMode: "limited",
    defaultScopes: ["use:llm_gateway"],
  });
  const currentTier = useSettings().tier;
  const { data: allScopeOptions = [], error: scopeOptionsError } = useSWR<
    PatScopeOption[]
  >(canCreateTokens ? SWR_KEYS.userPatScopes : null, errorHandlingFetcher, {
    fallbackData: [],
  });
  const scopeOptions = useMemo(
    () =>
      allScopeOptions.filter((option) =>
        tierAtLeast(currentTier ?? Tier.COMMUNITY, option.min_tier)
      ),
    [allScopeOptions, currentTier]
  );
  const canCreateGatewayToken =
    canCreateTokens &&
    canCreatePAT &&
    scopeOptions.some((option) => option.scope === "use:llm_gateway");

  return (
    <>
      {tokenCreation.showCreateModal && (
        <PATModal
          isCreating={tokenCreation.isCreating}
          newTokenName={tokenCreation.newTokenName}
          setNewTokenName={tokenCreation.setNewTokenName}
          expirationDays={tokenCreation.expirationDays}
          setExpirationDays={tokenCreation.setExpirationDays}
          accessMode={tokenCreation.accessMode}
          setAccessMode={tokenCreation.setAccessMode}
          scopeOptions={scopeOptions}
          scopesError={Boolean(scopeOptionsError)}
          selectedScopes={tokenCreation.selectedScopes}
          toggleScope={tokenCreation.toggleScope}
          onClose={tokenCreation.closeTokenModal}
          onCreate={tokenCreation.createPAT}
          createdToken={tokenCreation.newlyCreatedToken}
        />
      )}

      <GatewayAccessSection
        canCreateToken={canCreateGatewayToken}
        onCreateToken={tokenCreation.openTokenModal}
      />
    </>
  );
}

function AccountsAccessSettings() {
  const t = useTranslations("settings");
  const { user, authTypeMetadata, permissions } = useUser();
  const isMultiTenant = useIsMultiTenant();
  const [showPasswordModal, setShowPasswordModal] = useState(false);

  // TODO(auth-refresh): only passwordMinLength is enforced here; the remaining
  // constraints (max length, uppercase, lowercase, digit, special char) will be
  // wired up when this form is refreshed as part of auth-refresh.
  const passwordValidationSchema = Yup.object().shape({
    currentPassword: Yup.string().required("Current password is required"),
    newPassword: Yup.string()
      .min(
        authTypeMetadata?.passwordMinLength ?? 0,
        `Password must be at least ${authTypeMetadata?.passwordMinLength ?? 0} characters`
      )
      .required("New password is required"),
    confirmPassword: Yup.string()
      .oneOf([Yup.ref("newPassword")], "Passwords do not match")
      .required("Please confirm your new password"),
  });

  const [tokenToDelete, setTokenToDelete] = useState<PAT | null>(null);

  const canCreateTokens = useCloudSubscription();
  const canCreatePAT = hasPermission(
    permissions,
    Permission.CREATE_USER_API_KEYS
  );

  const showPasswordSection = Boolean(user?.password_configured);

  // Fetch PATs with SWR — always fetch when auth is available
  const {
    data: pats = [],
    mutate,
    error,
    isLoading,
  } = useSWR<PAT[]>(
    isMultiTenant !== null ? SWR_KEYS.userPats : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: true,
      dedupingInterval: 2000,
      fallbackData: [],
    }
  );

  // Hide the section entirely if user has no permission AND no existing tokens
  const showTokensSection =
    isMultiTenant !== null && (isLoading || canCreatePAT || pats.length > 0);

  const { data: allScopeOptions = [], error: scopeOptionsError } = useSWR<
    PatScopeOption[]
  >(
    showTokensSection && canCreateTokens ? SWR_KEYS.userPatScopes : null,
    errorHandlingFetcher,
    { fallbackData: [] }
  );
  const currentTier = useSettings().tier;
  const scopeOptions = useMemo(
    () =>
      // Undefined tier (settings loading/failed) must not hide Community scopes.
      allScopeOptions.filter((option) =>
        tierAtLeast(currentTier ?? Tier.COMMUNITY, option.min_tier)
      ),
    [allScopeOptions, currentTier]
  );
  const tokenCreation = usePATCreation({
    onCreateSuccess: async () => {
      await mutate();
    },
  });

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

  // Use filter hook for searching tokens
  const {
    query,
    setQuery,
    filtered: filteredPats,
  } = useFilter(pats, (pat) => `${pat.name} ${pat.token_display}`);

  // Show error popup if SWR fetch fails
  useEffect(() => {
    if (error) {
      toast.error(t("apiKeys.toasts.loadFailed"));
    }
  }, [error, t]);

  useEffect(() => {
    if (scopeOptionsError) {
      toast.error(t("apiKeys.toasts.loadPermissionsFailed"));
    }
  }, [scopeOptionsError, t]);

  const deletePAT = useCallback(
    async (patId: number) => {
      try {
        const response = await fetch(`/api/user/pats/${patId}`, {
          method: "DELETE",
        });

        if (response.ok) {
          // Clear the newly created token if it's the one being deleted
          if (tokenCreation.newlyCreatedToken?.id === patId) {
            tokenCreation.closeTokenModal();
          }
          await mutate();
          toast.success(t("apiKeys.toasts.deleted"));
          setTokenToDelete(null);
        } else {
          toast.error(t("apiKeys.toasts.deleteFailed"));
        }
      } catch (error) {
        toast.error(t("apiKeys.toasts.deleteNetworkError"));
      }
    },
    [mutate, tokenCreation, t]
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
          toast.success(t("accounts.passwordModal.toasts.updated"));
          setShowPasswordModal(false);
        } else {
          const errorData = await response.json();
          toast.error(
            errorData.detail || t("accounts.passwordModal.toasts.updateFailed")
          );
        }
      } catch (error) {
        toast.error(t("accounts.passwordModal.toasts.networkError"));
      }
    },
    [t]
  );

  return (
    <>
      {tokenCreation.showCreateModal && (
        <PATModal
          isCreating={tokenCreation.isCreating}
          newTokenName={tokenCreation.newTokenName}
          setNewTokenName={tokenCreation.setNewTokenName}
          expirationDays={tokenCreation.expirationDays}
          setExpirationDays={tokenCreation.setExpirationDays}
          accessMode={tokenCreation.accessMode}
          setAccessMode={tokenCreation.setAccessMode}
          scopeOptions={scopeOptions}
          scopesError={Boolean(scopeOptionsError)}
          selectedScopes={tokenCreation.selectedScopes}
          toggleScope={tokenCreation.toggleScope}
          onClose={tokenCreation.closeTokenModal}
          onCreate={tokenCreation.createPAT}
          createdToken={tokenCreation.newlyCreatedToken}
        />
      )}

      {tokenToDelete && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={t("apiKeys.revokeModal.title")}
          onClose={() => setTokenToDelete(null)}
          submit={
            <Button
              variant="danger"
              onClick={() => deletePAT(tokenToDelete.id)}
            >
              {t("apiKeys.revokeModal.submit")}
            </Button>
          }
        >
          <Section gap={2} alignItems="start">
            <Text color="text-05">
              {t("apiKeys.revokeModal.description", {
                name: tokenToDelete.name,
                tokenDisplay: tokenToDelete.token_display,
              })}
            </Text>
            <Text color="text-05">{t("apiKeys.revokeModal.question")}</Text>
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
                title={t("accounts.passwordModal.title")}
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
                      ? t("accounts.passwordModal.submit.updating")
                      : t("accounts.passwordModal.submit.update")}
                  </Button>
                }
                onClose={() => {
                  setShowPasswordModal(false);
                }}
              >
                <Section gap={4}>
                  <Section gap={1} alignItems="start">
                    <InputVertical
                      withLabel="currentPassword"
                      title={t("accounts.passwordModal.currentPassword.title")}
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
                  <Section gap={1} alignItems="start">
                    <InputVertical
                      withLabel="newPassword"
                      title={t("accounts.passwordModal.newPassword.title")}
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
                  <Section gap={1} alignItems="start">
                    <InputVertical
                      withLabel="confirmPassword"
                      title={t("accounts.passwordModal.confirmPassword.title")}
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

      <Section gap={8}>
        <Section gap={3}>
          <Content
            title={t("accounts.title")}
            sizePreset="main-content"
            variant="section"
            width="full"
          />
          <Card border="solid" rounding={4}>
            <Section alignItems="start" height="fit">
              <InputHorizontal
                title={t("accounts.email.title")}
                description={t("accounts.email.description")}
                center
              >
                <Text color="text-05">
                  {user?.email ?? t("accounts.email.anonymousFallback")}
                </Text>
              </InputHorizontal>

              {showPasswordSection && (
                <InputHorizontal
                  title={t("accounts.password.title")}
                  description={t("accounts.password.description")}
                  center
                >
                  <Button
                    prominence="secondary"
                    icon={SvgLock}
                    onClick={() => setShowPasswordModal(true)}
                    interaction={showPasswordModal ? "hover" : "rest"}
                  >
                    {t("accounts.password.changeButton")}
                  </Button>
                </InputHorizontal>
              )}
            </Section>
          </Card>
        </Section>

        {showTokensSection && (
          <Section gap={3}>
            <Content
              title={t("apiKeys.section.title")}
              sizePreset="main-content"
              variant="section"
              width="full"
            />
            {canCreateTokens ? (
              <Card border="solid" padding={1} rounding={4}>
                <Section alignItems="start" height="fit">
                  <Section gap={0}>
                    <Section flexDirection="row" padding={1} gap={2}>
                      {pats.length === 0 ? (
                        <Section
                          padding={2}
                          alignItems="start"
                          data-testid="access-token-list-status"
                        >
                          <Text font="secondary-body" color="text-03">
                            {isLoading
                              ? t("apiKeys.list.loading")
                              : t("apiKeys.list.empty")}
                          </Text>
                        </Section>
                      ) : (
                        <InputTypeIn
                          placeholder={t("apiKeys.list.searchPlaceholder")}
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
                          interaction={
                            tokenCreation.showCreateModal ? "active" : "rest"
                          }
                          onClick={tokenCreation.openTokenModal}
                          disabled={!canCreatePAT}
                          tooltip={
                            !canCreatePAT
                              ? t("apiKeys.list.noPermissionTooltip")
                              : undefined
                          }
                        >
                          {t("apiKeys.list.newTokenButton")}
                        </Button>
                      </div>
                    </Section>

                    <Section gap={1}>
                      {filteredPats.map((pat) => {
                        const now = new Date();
                        const createdDate = new Date(pat.created_at);
                        const daysSinceCreation = Math.floor(
                          (now.getTime() - createdDate.getTime()) /
                            (1000 * 60 * 60 * 24)
                        );

                        let expiryText = t("apiKeys.list.neverExpires");
                        if (pat.expires_at) {
                          const expiresDate = new Date(pat.expires_at);
                          const daysUntilExpiry = Math.ceil(
                            (expiresDate.getTime() - now.getTime()) /
                              (1000 * 60 * 60 * 24)
                          );
                          expiryText = t("apiKeys.list.expiresIn", {
                            count: daysUntilExpiry,
                          });
                        }

                        const scopeText =
                          pat.scopes === null
                            ? t(
                                "apiKeys.createModal.permissions.fullAccessOption"
                              )
                            : pat.scopes
                                .map((scope) => scopeLabels.get(scope) ?? scope)
                                .join(", ");

                        const createdText =
                          daysSinceCreation === 0
                            ? t("apiKeys.list.createdToday")
                            : t("apiKeys.list.createdDaysAgo", {
                                count: daysSinceCreation,
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
                                    aria-label={t(
                                      "apiKeys.list.deleteTokenAriaLabel",
                                      { name: pat.name }
                                    )}
                                  />
                                }
                              />
                            </div>
                          </Interactive.Container>
                        );
                      })}
                    </Section>
                  </Section>
                </Section>
              </Card>
            ) : (
              <Card border="solid" rounding={4}>
                <Section alignItems="start" height="fit">
                  <Section flexDirection="row" justifyContent="between">
                    <Text font="secondary-body" color="text-03">
                      {t("apiKeys.upsell.description")}
                    </Text>
                    <Button prominence="secondary" href="/admin/billing">
                      {t("apiKeys.upsell.upgradeButton")}
                    </Button>
                  </Section>
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
  const t = useTranslations("settings");
  const sourceMetadata = getSourceMetadata(source);

  return (
    <Card border="solid" rounding={4}>
      <Section alignItems="start" height="fit">
        <Content
          icon={sourceMetadata.icon}
          title={sourceMetadata.displayName}
          description={
            isActive
              ? t("connectors.status.connected")
              : t("connectors.status.paused")
          }
          sizePreset="main-content"
          variant="section"
        />
      </Section>
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
  const t = useTranslations("settings");
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [showDisconnectConfirmation, setShowDisconnectConfirmation] =
    useState(false);
  const sourceMetadata = getSourceMetadata(connector.source as ValidSources);

  const handleDisconnect = useCallback(async () => {
    setIsDisconnecting(true);
    try {
      const response = await fetch(
        `/api/federated/${connector.federated_connector_id}/oauth`,
        { method: "DELETE" }
      );

      if (response.ok) {
        toast.success(t("connectors.toasts.disconnected"));
        setShowDisconnectConfirmation(false);
        onDisconnectSuccess();
      } else {
        throw new Error("Failed to disconnect");
      }
    } catch (error) {
      toast.error(t("connectors.toasts.disconnectFailed"));
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
            t("connectors.disconnectModal.title", {
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
                ? t("connectors.disconnectModal.disconnecting")
                : t("connectors.disconnectModal.submit")}
            </Button>
          }
        >
          <Section gap={2} alignItems="start">
            <Text color="text-05">
              {t("connectors.disconnectModal.description", {
                name: sourceMetadata.displayName,
              })}
            </Text>
            <Text color="text-05">
              {t("connectors.disconnectModal.continueNote", {
                name: sourceMetadata.displayName,
              })}
            </Text>
          </Section>
        </ConfirmationModalLayout>
      )}

      <Card border="solid" padding={2} rounding={4}>
        <Section alignItems="start" height="fit">
          <ContentAction
            icon={sourceMetadata.icon}
            title={sourceMetadata.displayName}
            description={
              connector.has_oauth_token
                ? t("connectors.status.connected")
                : t("connectors.status.notConnected")
            }
            sizePreset="main-content"
            variant="section"
            padding={1}
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
                  {t("connectors.connectButton")}
                </Button>
              ) : undefined
            }
          />
        </Section>
      </Card>
    </>
  );
}

function ConnectorsSettings() {
  const t = useTranslations("settings");
  const {
    connectors: federatedConnectors,
    refetch: refetchFederatedConnectors,
  } = useFederatedOAuthStatus();
  const { ccPairs } = useCCPairs();

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
    <Section gap={8}>
      <Section gap={3} justifyContent="start">
        <Content
          title={t("connectors.title")}
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
            title={t("connectors.emptyMessage")}
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
  LLMGatewaySettings,
  ConnectorsSettings,
};
