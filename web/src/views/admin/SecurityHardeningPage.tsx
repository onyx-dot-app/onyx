"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import { useAuthTypeMetadata } from "@/lib/auth/hooks";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import InputNumber from "@/refresh-components/inputs/InputNumber";
import InputChipField, {
  type ChipItem,
} from "@/refresh-components/inputs/InputChipField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import {
  Content,
  InputHorizontal,
  InputVertical,
  Section,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { Card, InputTypeIn, Switch, Text } from "@opal/components";
import { markdown } from "@opal/utils";
import { useSettings } from "@/lib/settings/hooks";
import { Settings, toSettings } from "@/lib/settings/types";
import { updateAdminSettings } from "@/lib/settings/svc";
import type { RichStr } from "@opal/types";
import type {
  IncognitoAvailability,
  IncognitoRecordMode,
  SecuritySettings,
  SSRFProtectionLevel,
} from "@/lib/types";

const route = ADMIN_ROUTES.SECURITY_HARDENING;

// Technical literal, not copy — the characters the password policy accepts.
const SPECIAL_PASSWORD_CHARACTERS = "!@#$%^&*()_+-=[]{}|;:,.<>?";

// Write shape: a partial patch. The backend treats only the keys present in the
// PUT body as explicit overrides; absent keys keep their stored value, while an
// explicit `null` clears an override back to the env default (see
// `SecuritySettingsOverrides` + `present_keys` in the backend).
type SecuritySettingsUpdate = {
  [K in keyof SecuritySettings]?: SecuritySettings[K] | null;
};

interface ToggleRowProps {
  title: string;
  description?: string | RichStr;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
}

function ToggleRow({
  title,
  description,
  checked,
  onCheckedChange,
  disabled,
}: ToggleRowProps) {
  return (
    <InputHorizontal title={title} description={description} withLabel>
      <Switch
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
      />
    </InputHorizontal>
  );
}

interface JwtTextRowProps {
  title: string | RichStr;
  description: string | RichStr;
  value: string;
  placeholder: string;
  pinned: boolean;
  onCommit: (value: string) => Promise<void>;
}

function JwtTextRow({
  title,
  description,
  value,
  placeholder,
  pinned,
  onCommit,
}: JwtTextRowProps) {
  const t = useTranslations("admin.security");
  const [text, setText] = useState(value);
  // The revision bump resyncs after a commit settles even when `value` did not
  // move, e.g. a failed clear where the optimistic patch drops nulls. A focused
  // field is being edited, so the resync waits for the next blur.
  const [revision, setRevision] = useState(0);
  const [focused, setFocused] = useState(false);
  // Commit only text the user typed this focus. A frozen unedited field must
  // not overwrite a value that moved underneath it (another tab, env change).
  const dirty = useRef(false);
  useEffect(() => {
    if (!focused) setText(value);
  }, [value, revision, focused]);

  if (pinned) {
    // An input promises editability. A pinned value is display-only.
    return (
      <InputVertical
        title={title}
        description={t("jwt.pinnedField.description")}
        withLabel
      >
        <Text font="main-ui-body" color="text-03">
          {value}
        </Text>
      </InputVertical>
    );
  }

  return (
    <InputVertical title={title} description={description} withLabel>
      <InputTypeIn
        value={text}
        placeholder={placeholder}
        onChange={(e) => {
          dirty.current = true;
          setText(e.target.value);
        }}
        onFocus={() => {
          dirty.current = false;
          setFocused(true);
        }}
        onBlur={async () => {
          setFocused(false);
          const next = text.trim();
          if (!dirty.current || next === value) return;
          dirty.current = false;
          await onCommit(next);
          setRevision((r) => r + 1);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
      />
    </InputVertical>
  );
}

export default function SecurityHardeningPage() {
  const t = useTranslations("admin.security");
  const isMultiTenant = NEXT_PUBLIC_CLOUD_ENABLED;
  const { authTypeMetadata, isLoading: authTypeLoading } =
    useAuthTypeMetadata();
  // Single-tenant at runtime, not just by build flag. The explicit === false
  // waits for the fetch, metadata is undefined while loading or unreachable.
  const isSingleTenantRuntime =
    !authTypeLoading && authTypeMetadata?.multiTenant === false;
  // The kill switch only enforces on single-tenant deployments, so the
  // card hides where the backend would refuse the save.
  const showPasswordLockdown = !isMultiTenant && isSingleTenantRuntime;

  const { data: settings, isLoading: settingsLoading } =
    useSWR<SecuritySettings>(
      SWR_KEYS.adminSecuritySettings,
      errorHandlingFetcher
    );

  // Invite-only lives in workspace settings, not SecuritySettings, so it has
  // its own save path.
  const workspaceSettings = useSettings();
  const saveWorkspaceSettings = useCallback(
    async (updates: Partial<Settings>) => {
      const newSettings: Settings = {
        ...toSettings(workspaceSettings),
        ...updates,
      };
      try {
        await mutate(
          SWR_KEYS.settings,
          async () => {
            await updateAdminSettings(newSettings);
            return newSettings;
          },
          {
            optimisticData: newSettings,
            revalidate: true,
            rollbackOnError: true,
          }
        );
        toast.success(t("toasts.settingsUpdated"));
      } catch (err) {
        console.error("Failed to update workspace settings", err);
        const message =
          err instanceof Error && err.message
            ? err.message
            : t("toasts.settingsUpdateFailed");
        toast.error(message);
      }
    },
    [workspaceSettings, t]
  );
  const { data: pinnedFields } = useSWR<string[]>(
    SWR_KEYS.adminSecurityPinnedFields,
    errorHandlingFetcher
  );

  // Local state mirrors the loaded settings. We save on every committed change.
  const [draft, setDraft] = useState<SecuritySettings | null>(null);
  const [domainInput, setDomainInput] = useState("");
  // The "Restrict Email Domains" toggle has no backing field — restriction is
  // active iff the allowlist is non-empty. This lets an admin turn the toggle on
  // and reveal the (still empty) input before typing the first domain. It stays
  // independent of `draft` so unrelated saves don't collapse the open input.
  const [forceShowDomains, setForceShowDomains] = useState(false);
  // Saves are serialized through a promise chain: overlapping PUTs cannot
  // exist. Only the last queued save adopts the server response, so a
  // mid-queue response never erases a later edit's optimistic state (which
  // full-value fields like the domain list read back at click time).
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const savesQueued = useRef(0);

  useEffect(() => {
    // Queued saves own the draft, their optimistic state must survive a cache
    // update landing mid-queue.
    if (settings && savesQueued.current === 0) setDraft(settings);
  }, [settings]);

  const doSave = useCallback(
    async (updates: SecuritySettingsUpdate) => {
      try {
        const response = await fetch(SWR_KEYS.adminSecuritySettings, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          // Send ONLY the changed fields. The backend persists each present key
          // as an explicit override and lets absent keys fall back to env
          // defaults. Sending the full settings would freeze every env default
          // as an override and 403 on operator-locked fields in multi-tenant.
          body: JSON.stringify(updates),
        });
        if (!response.ok) {
          const errorMsg = (await response.json()).detail;
          throw new Error(errorMsg);
        }
        // PUT returns the new effective settings — adopt them as the source of
        // truth so the UI matches what was actually persisted/merged.
        const effective: SecuritySettings = await response.json();
        if (savesQueued.current === 1) {
          setDraft(effective);
          await mutate(SWR_KEYS.adminSecuritySettings, effective, {
            revalidate: false,
          });
        }
        toast.success(t("toasts.securitySettingsUpdated"));
      } catch (error) {
        // Re-sync from the server (the source of truth) rather than a possibly
        // stale local snapshot — a late failure must not clobber other edits
        // that may have succeeded while this request was in flight.
        try {
          if (savesQueued.current === 1) {
            const fresh = await mutate<SecuritySettings>(
              SWR_KEYS.adminSecuritySettings
            );
            // Re-checked after the await: an edit queued during the fetch owns
            // the draft now.
            if (fresh && savesQueued.current === 1) setDraft(fresh);
          }
        } catch {
          // If revalidation also fails (e.g. network down), the optimistic
          // update stays until the next successful SWR refresh (e.g. focus).
        }
        const message =
          error instanceof Error
            ? error.message
            : t("toasts.securitySettingsUpdateFailed");
        toast.error(message);
      }
    },
    [t]
  );

  const saveSettings = useCallback(
    (updates: SecuritySettingsUpdate) => {
      // Applied at enqueue so a full-value edit (the domain list) reads every
      // queued change off `draft`. A null keeps the current value, its env
      // default only arrives with the PUT response.
      setDraft((prev) => {
        if (!prev) return prev;
        const concrete = Object.fromEntries(
          Object.entries(updates).filter(([, value]) => value != null)
        ) as Partial<SecuritySettings>;
        return { ...prev, ...concrete };
      });
      savesQueued.current += 1;
      const run = saveQueue.current
        .then(() => doSave(updates))
        .finally(() => {
          savesQueued.current -= 1;
        });
      // doSave never rejects, the catch keeps the chain alive regardless.
      saveQueue.current = run.catch(() => undefined);
      return run;
    },
    [doSave]
  );

  if (settingsLoading || !draft) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header icon={route.icon} title={route.title} divider />
        <SettingsLayouts.Body />
      </SettingsLayouts.Root>
    );
  }

  const validDomains: ChipItem[] = draft.valid_email_domains.map((domain) => ({
    id: domain,
    label: domain,
  }));

  // Show the domain allowlist when it's populated, or when the admin has
  // explicitly turned the restriction on but not yet added a domain.
  const showDomains = forceShowDomains || draft.valid_email_domains.length > 0;

  function addDomain(value: string) {
    const trimmed = value.trim().toLowerCase();
    if (!trimmed) return;
    const current = draft?.valid_email_domains ?? [];
    if (current.includes(trimmed)) {
      setDomainInput("");
      return;
    }
    void saveSettings({ valid_email_domains: [...current, trimmed] });
    setDomainInput("");
  }

  function removeDomain(id: string) {
    const current = draft?.valid_email_domains ?? [];
    void saveSettings({
      valid_email_domains: current.filter((domain) => domain !== id),
    });
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description={t("page.description")}
        divider
      />

      <SettingsLayouts.Body>
        {/* Authentication */}
        <div className="flex w-full flex-col gap-3">
          <Content
            title={t("authentication.section.title")}
            sizePreset="main-content"
            variant="section"
          />

          <Card border="solid" rounding={4}>
            <Section>
              <ToggleRow
                title={t("authentication.idpExpiry.title")}
                description={t("authentication.idpExpiry.description")}
                checked={draft.track_external_idp_expiry}
                onCheckedChange={(checked) =>
                  void saveSettings({ track_external_idp_expiry: checked })
                }
              />

              {!isMultiTenant && (
                <>
                  {isSingleTenantRuntime && (
                    <ToggleRow
                      title={t("authentication.openSignUp.title")}
                      description={t("authentication.openSignUp.description")}
                      checked={workspaceSettings.invite_only_enabled ?? false}
                      onCheckedChange={(checked) =>
                        void saveWorkspaceSettings({
                          invite_only_enabled: checked,
                        })
                      }
                    />
                  )}

                  <ToggleRow
                    title={t("authentication.emailDomains.title")}
                    description={t("authentication.emailDomains.description")}
                    checked={showDomains}
                    onCheckedChange={(checked) => {
                      if (checked) {
                        setForceShowDomains(true);
                      } else {
                        // Clearing the allowlist disables the restriction.
                        setForceShowDomains(false);
                        void saveSettings({ valid_email_domains: [] });
                      }
                    }}
                  />

                  {showDomains && (
                    <InputVertical
                      title={t("authentication.allowedEmailDomains.title")}
                      subDescription={t(
                        "authentication.allowedEmailDomains.subDescription"
                      )}
                      withLabel
                    >
                      <InputChipField
                        chips={validDomains}
                        onRemoveChip={removeDomain}
                        onAdd={addDomain}
                        value={domainInput}
                        onChange={setDomainInput}
                        placeholder={t(
                          "authentication.allowedEmailDomains.placeholder"
                        )}
                      />
                    </InputVertical>
                  )}
                </>
              )}

              {showPasswordLockdown && (
                <ToggleRow
                  title={t("authentication.passwordLockdown.title")}
                  description={t("authentication.passwordLockdown.description")}
                  checked={!draft.password_auth_enabled}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_auth_enabled: !checked })
                  }
                />
              )}
            </Section>
          </Card>

          {/* Password policy (single-tenant only) */}
          {!isMultiTenant && (
            <Card border="solid" rounding={4}>
              <Section>
                <Content
                  title={t("passwordPolicy.section.title")}
                  description={t("passwordPolicy.section.description")}
                  sizePreset="main-ui"
                  variant="section"
                />

                <div className="flex w-full items-start gap-4">
                  <div className="flex-1">
                    <InputVertical
                      title={t("passwordPolicy.minLength.title")}
                      suffix={t("passwordPolicy.charactersSuffix.label")}
                      withLabel
                    >
                      <InputNumber
                        value={draft.password_min_length}
                        onChange={(value) =>
                          void saveSettings({ password_min_length: value })
                        }
                        min={1}
                        max={1024}
                        placeholder={t(
                          "passwordPolicy.lengthInput.placeholder"
                        )}
                      />
                    </InputVertical>
                  </div>
                  <div className="flex-1">
                    <InputVertical
                      title={t("passwordPolicy.maxLength.title")}
                      suffix={t("passwordPolicy.charactersSuffix.label")}
                      withLabel
                    >
                      <InputNumber
                        value={draft.password_max_length}
                        onChange={(value) =>
                          void saveSettings({ password_max_length: value })
                        }
                        min={1}
                        max={1024}
                        placeholder={t(
                          "passwordPolicy.lengthInput.placeholder"
                        )}
                      />
                    </InputVertical>
                  </div>
                </div>

                <ToggleRow
                  title={t("passwordPolicy.requireUppercase.title")}
                  checked={draft.password_require_uppercase}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_uppercase: checked })
                  }
                />

                <ToggleRow
                  title={t("passwordPolicy.requireLowercase.title")}
                  checked={draft.password_require_lowercase}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_lowercase: checked })
                  }
                />

                <ToggleRow
                  title={t("passwordPolicy.requireNumber.title")}
                  checked={draft.password_require_digit}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_digit: checked })
                  }
                />

                <ToggleRow
                  title={t("passwordPolicy.requireSpecialChar.title")}
                  description={markdown(
                    // Kept as an argument: the literal contains `{}`, which ICU
                    // would otherwise parse as a message argument.
                    t("passwordPolicy.requireSpecialChar.description", {
                      characters: SPECIAL_PASSWORD_CHARACTERS,
                    })
                  )}
                  checked={draft.password_require_special_char}
                  onCheckedChange={(checked) =>
                    void saveSettings({
                      password_require_special_char: checked,
                    })
                  }
                />
              </Section>
            </Card>
          )}

          {/* External JWT auth (single-tenant only). Absent while the
              pinned state is unknown, editability must never fail open. */}
          {!isMultiTenant && pinnedFields && (
            <Card border="solid" rounding={4}>
              <Section>
                <Content
                  title={t("jwt.section.title")}
                  description={t("jwt.section.description")}
                  sizePreset="main-ui"
                  variant="section"
                />

                <JwtTextRow
                  title={t("jwt.publicKeyUrl.title")}
                  description={t("jwt.publicKeyUrl.description")}
                  value={draft.jwt_public_key_url ?? ""}
                  placeholder="https://idp.example.com/.well-known/jwks.json"
                  pinned={pinnedFields.includes("jwt_public_key_url")}
                  onCommit={(value) =>
                    saveSettings({ jwt_public_key_url: value || null })
                  }
                />

                <JwtTextRow
                  title={t("jwt.expectedAudience.title")}
                  description={t("jwt.expectedAudience.description")}
                  value={draft.jwt_expected_audience ?? ""}
                  placeholder="onyx"
                  pinned={pinnedFields.includes("jwt_expected_audience")}
                  onCommit={(value) =>
                    saveSettings({ jwt_expected_audience: value || null })
                  }
                />

                <JwtTextRow
                  title={t("jwt.expectedIssuer.title")}
                  description={t("jwt.expectedIssuer.description")}
                  value={draft.jwt_expected_issuer ?? ""}
                  placeholder="https://idp.example.com"
                  pinned={pinnedFields.includes("jwt_expected_issuer")}
                  onCommit={(value) =>
                    saveSettings({ jwt_expected_issuer: value || null })
                  }
                />
              </Section>
            </Card>
          )}
        </div>

        {/* Admin Controls */}
        <div className="flex w-full flex-col gap-3">
          <Content
            title={t("adminControls.section.title")}
            sizePreset="main-content"
            variant="section"
          />

          <Card border="solid" rounding={4}>
            <Section>
              <InputHorizontal
                title={t("adminControls.userDirectory.title")}
                description={t("adminControls.userDirectory.description")}
                withLabel
                responsive
              >
                <div className="w-full sm:w-60">
                  <InputSelect
                    value={
                      draft.user_directory_admin_only
                        ? "admins_only"
                        : "all_users"
                    }
                    onValueChange={(value) =>
                      void saveSettings({
                        user_directory_admin_only: value === "admins_only",
                      })
                    }
                  >
                    <InputSelect.Trigger />
                    <InputSelect.Content>
                      <InputSelect.Item
                        value="all_users"
                        wrapDescription
                        description={t(
                          "adminControls.userDirectory.allUsers.description"
                        )}
                      >
                        {t("adminControls.userDirectory.allUsers.label")}
                      </InputSelect.Item>
                      <InputSelect.Item
                        value="admins_only"
                        wrapDescription
                        description={t(
                          "adminControls.userDirectory.adminsOnly.description"
                        )}
                      >
                        {t("adminControls.userDirectory.adminsOnly.label")}
                      </InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelect>
                </div>
              </InputHorizontal>

              <InputHorizontal
                title={t("adminControls.incognito.title")}
                description={t("adminControls.incognito.description")}
                withLabel
                responsive
              >
                <div className="w-full sm:w-60">
                  <InputSelect
                    value={draft.incognito_availability}
                    onValueChange={async (value) => {
                      await saveSettings({
                        incognito_availability: value as IncognitoAvailability,
                      });
                      await mutate(SWR_KEYS.incognitoAvailability);
                    }}
                  >
                    <InputSelect.Trigger />
                    <InputSelect.Content>
                      <InputSelect.Item
                        value="off"
                        wrapDescription
                        description={t(
                          "adminControls.incognito.off.description"
                        )}
                      >
                        {t("adminControls.incognito.off.label")}
                      </InputSelect.Item>
                      <InputSelect.Item
                        value="everyone"
                        wrapDescription
                        description={t(
                          "adminControls.incognito.everyone.description"
                        )}
                      >
                        {t("adminControls.incognito.everyone.label")}
                      </InputSelect.Item>
                      <InputSelect.Item
                        value="groups"
                        wrapDescription
                        description={t(
                          "adminControls.incognito.groups.description"
                        )}
                      >
                        {t("adminControls.incognito.groups.label")}
                      </InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelect>
                </div>
              </InputHorizontal>

              <InputHorizontal
                title={t("adminControls.incognitoRecords.title")}
                description={t("adminControls.incognitoRecords.description")}
                withLabel
                responsive
              >
                <div className="w-full sm:w-60">
                  <InputSelect
                    value={draft.incognito_record_mode}
                    onValueChange={(value) =>
                      void saveSettings({
                        incognito_record_mode: value as IncognitoRecordMode,
                      })
                    }
                  >
                    <InputSelect.Trigger />
                    <InputSelect.Content>
                      <InputSelect.Item
                        value="usage_only"
                        wrapDescription
                        description={t(
                          "adminControls.incognitoRecords.usageOnly.description"
                        )}
                      >
                        {t("adminControls.incognitoRecords.usageOnly.label")}
                      </InputSelect.Item>
                      <InputSelect.Item
                        value="full_history"
                        wrapDescription
                        description={t(
                          "adminControls.incognitoRecords.fullHistory.description"
                        )}
                      >
                        {t("adminControls.incognitoRecords.fullHistory.label")}
                      </InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelect>
                </div>
              </InputHorizontal>

              {!isMultiTenant && (
                <InputHorizontal
                  title={t("adminControls.maskCredentials.title")}
                  description={t("adminControls.maskCredentials.description")}
                  withLabel
                  responsive
                >
                  <div className="w-full sm:w-60">
                    <InputSelect
                      value={
                        draft.mask_credential_prefix ? "masked" : "visible"
                      }
                      onValueChange={(value) =>
                        void saveSettings({
                          mask_credential_prefix: value === "masked",
                        })
                      }
                    >
                      <InputSelect.Trigger />
                      <InputSelect.Content>
                        <InputSelect.Item
                          value="masked"
                          wrapDescription
                          description={t(
                            "adminControls.maskCredentials.masked.description"
                          )}
                        >
                          {t("adminControls.maskCredentials.masked.label")}
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="visible"
                          wrapDescription
                          description={t(
                            "adminControls.maskCredentials.visible.description"
                          )}
                        >
                          {t("adminControls.maskCredentials.visible.label")}
                        </InputSelect.Item>
                      </InputSelect.Content>
                    </InputSelect>
                  </div>
                </InputHorizontal>
              )}
            </Section>
          </Card>
        </div>

        {/* Network Safety. The env-injection toggle is always shown but locked
            off in multi-tenant cloud; the SSRF policy is single-tenant only
            (operator-controlled, env-driven in multi-tenant cloud). */}
        <div className="flex w-full flex-col gap-3">
          <Content
            title={t("networkSafety.section.title")}
            sizePreset="main-content"
            variant="section"
          />

          <Card border="solid" rounding={4}>
            <Section>
              <ToggleRow
                title={t("networkSafety.envInjection.title")}
                description={
                  isMultiTenant
                    ? t("networkSafety.envInjection.multiTenantDescription")
                    : t("networkSafety.envInjection.description")
                }
                checked={draft.llm_custom_config_env_injection}
                onCheckedChange={(checked) =>
                  void saveSettings({
                    llm_custom_config_env_injection: checked,
                  })
                }
                disabled={isMultiTenant}
              />

              {!isMultiTenant && (
                <InputHorizontal
                  title={t("networkSafety.ssrf.title")}
                  description={t("networkSafety.ssrf.description")}
                  withLabel
                  responsive
                >
                  <div className="w-full sm:w-60">
                    <InputSelect
                      value={draft.ssrf_protection_level}
                      onValueChange={(value) =>
                        void saveSettings({
                          ssrf_protection_level: value as SSRFProtectionLevel,
                        })
                      }
                    >
                      <InputSelect.Trigger />
                      <InputSelect.Content>
                        <InputSelect.Item
                          value="validate_all"
                          wrapDescription
                          description={t(
                            "networkSafety.ssrf.validateAll.description"
                          )}
                        >
                          {t("networkSafety.ssrf.validateAll.label")}
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="validate_llm"
                          wrapDescription
                          description={t(
                            "networkSafety.ssrf.validateLlm.description"
                          )}
                        >
                          {t("networkSafety.ssrf.validateLlm.label")}
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="allow_private_network"
                          wrapDescription
                          description={t(
                            "networkSafety.ssrf.allowPrivateNetwork.description"
                          )}
                        >
                          {t("networkSafety.ssrf.allowPrivateNetwork.label")}
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="disabled"
                          wrapDescription
                          description={t(
                            "networkSafety.ssrf.disabled.description"
                          )}
                        >
                          {t("networkSafety.ssrf.disabled.label")}
                        </InputSelect.Item>
                      </InputSelect.Content>
                    </InputSelect>
                  </div>
                </InputHorizontal>
              )}
            </Section>
          </Card>
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
