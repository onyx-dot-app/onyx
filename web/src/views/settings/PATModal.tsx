"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  ConfirmationModalLayout,
  InputVertical,
  Section,
  toast,
} from "@opal/layouts";
import { SvgKey } from "@opal/icons";
import {
  BasicModalFooter,
  Button,
  Code,
  CopyButton,
  InputCheckbox,
  InputSingleSelect,
  InputTypeIn,
  Modal,
  Text,
  useCreateModal,
} from "@opal/components";
import type { ErrorResponseBody } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  AccessMode,
  CreatedPAT,
  PatScopeOption,
} from "@/views/settings/types";

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
      <Text as="p" font="secondary-body" color="text-03">
        {t("apiKeys.scopeSelector.loadError")}
      </Text>
    );
  }
  if (scopeOptions.length === 0) {
    return (
      <Text as="p" font="secondary-body" color="text-03">
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
    // Two groups per row in the modal: each group starts at 12rem and grows.
    <Section
      flexDirection="row"
      justifyContent="start"
      alignItems="start"
      height="fit"
      gap={0}
      wrap
    >
      {groups.map((group) => (
        <Section
          key={group.label}
          justifyContent="start"
          alignItems="start"
          height="fit"
          gap={1}
          grow={1}
          basis={12}
        >
          <Text as="p" font="main-ui-action" color="text-04">
            {group.label}
          </Text>
          {group.rows.map((option) => {
            const lockReason = lockedBy.get(option.scope);
            const locked = lockReason !== undefined;
            return (
              <Section
                key={option.scope}
                flexDirection="row"
                justifyContent="start"
                alignItems="start"
                height="fit"
                gap={2}
                className="ms-2"
              >
                <InputCheckbox
                  checked={selectedScopes.includes(option.scope) || locked}
                  disabled={disabled || locked}
                  onCheckedChange={() => toggleScope(option.scope)}
                  aria-label={`${group.label} ${option.label}`}
                />
                <Section
                  justifyContent="start"
                  alignItems="start"
                  height="fit"
                  gap={0}
                >
                  <Text as="p" font="main-ui-body" color="text-04">
                    {lockReason !== undefined
                      ? t("apiKeys.scopeSelector.includedWith", {
                          label: option.label,
                          lockReason,
                        })
                      : option.label}
                  </Text>
                  {/* Fixed 2-line slot so every row is the same height. */}
                  <div className="h-8 overflow-hidden">
                    <Text
                      as="p"
                      font="secondary-body"
                      color="text-03"
                      maxLines={2}
                    >
                      {option.description}
                    </Text>
                  </div>
                </Section>
              </Section>
            );
          })}
        </Section>
      ))}
    </Section>
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
  /** The access mode the modal opened with; the select never empties below it. */
  defaultAccessMode: AccessMode;
  scopeOptions: PatScopeOption[];
  scopesError: boolean;
  selectedScopes: string[];
  toggleScope: (scope: string) => void;
  onClose: () => void;
  onCreate: () => void;
  createdToken: CreatedTokenState | null;
}

export function PATModal({
  isCreating,
  newTokenName,
  setNewTokenName,
  expirationDays,
  setExpirationDays,
  accessMode,
  setAccessMode,
  defaultAccessMode,
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
          <InputSingleSelect
            value={expirationDays}
            onValueChange={setExpirationDays}
            disabled={isCreating}
            defaultOption="30"
            placeholder={t("apiKeys.createModal.expiration.placeholder")}
            options={[
              { value: "7", title: t("apiKeys.createModal.expiration.days7") },
              {
                value: "30",
                title: t("apiKeys.createModal.expiration.days30"),
              },
              {
                value: "365",
                title: t("apiKeys.createModal.expiration.days365"),
              },
              {
                value: "null",
                title: t("apiKeys.createModal.expiration.noExpiration"),
              },
            ]}
          />
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
          <InputSingleSelect
            value={accessMode}
            // SAFETY: the options are the two AccessMode values.
            onValueChange={(value) => setAccessMode(value as AccessMode)}
            disabled={isCreating}
            defaultOption={defaultAccessMode}
            placeholder={t("apiKeys.createModal.permissions.placeholder")}
            options={[
              {
                value: "full",
                title: t("apiKeys.createModal.permissions.fullAccessOption"),
              },
              {
                value: "limited",
                title: t("apiKeys.createModal.permissions.limitedAccessOption"),
              },
            ]}
          />
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
}

export function usePATCreation({
  defaultName = "",
  defaultAccessMode = "full",
  defaultScopes = [],
}: UsePATCreationOptions = {}) {
  const t = useTranslations("settings");
  const { mutate } = useSWRConfig();
  const createModal = useCreateModal();
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
    createModal.toggle(true);
  }, [reset, createModal.toggle]);

  // The next open resets the draft, so the modal keeps its content while it
  // animates out.
  const closeTokenModal = useCallback(() => {
    createModal.toggle(false);
  }, [createModal.toggle]);

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
        const data: CreatedPAT = await response.json();
        setNewlyCreatedToken({
          id: data.id,
          token: data.token,
          name: newTokenName,
        });
        await mutate(SWR_KEYS.userPats);
      } else {
        const errorData: ErrorResponseBody = await response.json();
        toast.error(errorData.detail || t("apiKeys.toasts.createFailed"));
      }
    } catch (error) {
      console.error("Failed to create access token", error);
      toast.error(t("apiKeys.toasts.createNetworkError"));
    } finally {
      setIsCreating(false);
    }
  }, [accessMode, expirationDays, mutate, newTokenName, selectedScopes, t]);

  return {
    showCreateModal: createModal.isOpen,
    CreateModalProvider: createModal.Provider,
    isCreating,
    newTokenName,
    setNewTokenName,
    expirationDays,
    setExpirationDays,
    accessMode,
    setAccessMode,
    defaultAccessMode,
    selectedScopes,
    toggleScope,
    newlyCreatedToken,
    openTokenModal,
    closeTokenModal,
    createPAT,
  };
}
