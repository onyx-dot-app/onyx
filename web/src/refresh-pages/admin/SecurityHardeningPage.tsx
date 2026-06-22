"use client";

import { useCallback, useEffect, useState } from "react";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useTranslation } from "react-i18next";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { toast } from "@/hooks/useToast";
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
} from "@opal/layouts";
import { Card, Switch } from "@opal/components";
import { markdown } from "@opal/utils";
import type { RichStr } from "@opal/types";

const route = ADMIN_ROUTES.SECURITY_HARDENING;

// Outbound-request validation policy. Mirrors `SSRFProtectionLevel`
// in backend/onyx/server/security/models.py.
type SSRFProtectionLevel =
  | "validate_all"
  | "validate_llm"
  | "allow_private_network"
  | "disabled";

// Read shape: the effective, env-merged settings returned by GET /admin/security.
// Every field is concrete — the backend never returns null here (see
// `SecuritySettings` in backend/onyx/server/security/models.py).
interface SecuritySettings {
  user_directory_admin_only: boolean;
  track_external_idp_expiry: boolean;
  ssrf_protection_level: SSRFProtectionLevel;
  mask_credential_prefix: boolean;
  valid_email_domains: string[];
  password_min_length: number;
  password_max_length: number;
  password_require_uppercase: boolean;
  password_require_lowercase: boolean;
  password_require_digit: boolean;
  password_require_special_char: boolean;
}

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
}

function ToggleRow({
  title,
  description,
  checked,
  onCheckedChange,
}: ToggleRowProps) {
  return (
    <InputHorizontal title={title} description={description} withLabel>
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
    </InputHorizontal>
  );
}

export default function SecurityHardeningPage() {
  const { t } = useTranslation();
  const isMultiTenant = NEXT_PUBLIC_CLOUD_ENABLED;

  const { data: settings, isLoading: settingsLoading } =
    useSWR<SecuritySettings>(
      SWR_KEYS.adminSecuritySettings,
      errorHandlingFetcher
    );

  // Local state mirrors the loaded settings; we save on every change.
  const [draft, setDraft] = useState<SecuritySettings | null>(null);
  const [domainInput, setDomainInput] = useState("");
  // The "Restrict Email Domains" toggle has no backing field — restriction is
  // active iff the allowlist is non-empty. This lets an admin turn the toggle on
  // and reveal the (still empty) input before typing the first domain. It stays
  // independent of `draft` so unrelated saves don't collapse the open input.
  const [forceShowDomains, setForceShowDomains] = useState(false);

  useEffect(() => {
    if (settings) setDraft(settings);
  }, [settings]);

  const saveSettings = useCallback(async (updates: SecuritySettingsUpdate) => {
    // Optimistically reflect concrete changes for snappy toggles. A `null`
    // clears an override; its resolved env default only arrives with the PUT
    // response, so we leave the current value in place rather than guess.
    setDraft((prev) => {
      if (!prev) return prev;
      const concrete = Object.fromEntries(
        Object.entries(updates).filter(([, value]) => value != null)
      ) as Partial<SecuritySettings>;
      return { ...prev, ...concrete };
    });
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
      setDraft(effective);
      await mutate(SWR_KEYS.adminSecuritySettings, effective, {
        revalidate: false,
      });
      toast.success(t("admin.security.settings_updated", "Security settings updated"));
    } catch (error) {
      // Re-sync from the server (the source of truth) rather than a possibly
      // stale local snapshot — a late failure must not clobber other edits
      // that may have succeeded while this request was in flight.
      try {
        const fresh = await mutate<SecuritySettings>(
          SWR_KEYS.adminSecuritySettings
        );
        if (fresh) setDraft(fresh);
      } catch {
        // If revalidation also fails (e.g. network down), the optimistic
        // update stays until the next successful SWR refresh (e.g. focus).
      }
      const message =
        error instanceof Error
          ? error.message
          : t("admin.security.settings_update_failed", "Failed to update security settings");
      toast.error(message);
    }
  }, [t]);

  const routeTranslationKey = route.path.replace(/^\/admin\//, "").replace(/[/-]/g, "_");

  if (settingsLoading || !draft) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={t(`admin.sidebar.routes.${routeTranslationKey}`, route.title)}
          divider
        />
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
        title={t(`admin.sidebar.routes.${routeTranslationKey}`, route.title)}
        description={t("admin.security.header_description", "Runtime-configurable security settings. Unset values fall back to your deployment's environment configuration.")}
        divider
      />

      <SettingsLayouts.Body>
        {/* Authentication */}
        <div className="flex w-full flex-col gap-3">
          <Content
            title={t("admin.security.authentication", "Authentication")}
            sizePreset="main-content"
            variant="section"
          />

          <Card border="solid" rounding="lg">
            <Section>
              <ToggleRow
                title={t("admin.security.sync_expiry", "Sync Session Expiry with Identity Provider")}
                description={t("admin.security.sync_expiry_description", "Log users out when the upstream OAuth/OIDC provider session expires.")}
                checked={draft.track_external_idp_expiry}
                onCheckedChange={(checked) =>
                  void saveSettings({ track_external_idp_expiry: checked })
                }
              />

              {!isMultiTenant && (
                <>
                  <ToggleRow
                    title={t("admin.security.restrict_email_domains", "Restrict Email Domains")}
                    description={t("admin.security.restrict_email_domains_description", "Limit new user registrations to specific email domains.")}
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
                      title={t("admin.security.allowed_email_domains", "Allowed Email Domains")}
                      subDescription={t("admin.security.allowed_email_domains_description", "New users can only register new accounts with emails in this domain list.")}
                      withLabel
                    >
                      <InputChipField
                        chips={validDomains}
                        onRemoveChip={removeDomain}
                        onAdd={addDomain}
                        value={domainInput}
                        onChange={setDomainInput}
                        placeholder={t("admin.security.add_domain_placeholder", "Add a domain (e.g. onyx.app)")}
                      />
                    </InputVertical>
                  )}
                </>
              )}
            </Section>
          </Card>

          {/* Password policy (single-tenant only) */}
          {!isMultiTenant && (
            <Card border="solid" rounding="lg">
              <Section>
                <Content
                  title={t("admin.security.password_policy", "Password Policy")}
                  description={t("admin.security.password_policy_description", "Requirements for all new passwords. Applies to basic auth only.")}
                  sizePreset="main-ui"
                  variant="section"
                />

                <div className="flex w-full items-start gap-4">
                  <div className="flex-1">
                    <InputVertical
                      title={t("admin.security.min_password_length", "Minimum Password Length")}
                      suffix={t("admin.security.characters", "(characters)")}
                      withLabel
                    >
                      <InputNumber
                        value={draft.password_min_length}
                        onChange={(value) =>
                          void saveSettings({ password_min_length: value })
                        }
                        min={1}
                        max={1024}
                        placeholder={t("admin.security.default_placeholder", "Default")}
                      />
                    </InputVertical>
                  </div>
                  <div className="flex-1">
                    <InputVertical
                      title={t("admin.security.max_password_length", "Maximum Password Length")}
                      suffix={t("admin.security.characters", "(characters)")}
                      withLabel
                    >
                      <InputNumber
                        value={draft.password_max_length}
                        onChange={(value) =>
                          void saveSettings({ password_max_length: value })
                        }
                        min={1}
                        max={1024}
                        placeholder={t("admin.security.default_placeholder", "Default")}
                      />
                    </InputVertical>
                  </div>
                </div>

                <ToggleRow
                  title={t("admin.security.require_uppercase", "Require Uppercase Letter")}
                  checked={draft.password_require_uppercase}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_uppercase: checked })
                  }
                />

                <ToggleRow
                  title={t("admin.security.require_lowercase", "Require Lowercase Letter")}
                  checked={draft.password_require_lowercase}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_lowercase: checked })
                  }
                />

                <ToggleRow
                  title={t("admin.security.require_number", "Require Number")}
                  checked={draft.password_require_digit}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_digit: checked })
                  }
                />

                <ToggleRow
                  title={t("admin.security.require_special_char", "Require Special Characters")}
                  description={markdown(
                    t("admin.security.special_chars_description", "Accepted characters: `!@#$%^&*()_+-=[]{}|;:,.<>?`")
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
        </div>

        {/* Admin Controls */}
        <div className="flex w-full flex-col gap-3">
          <Content
            title={t("admin.security.admin_controls", "Admin Controls")}
            sizePreset="main-content"
            variant="section"
          />

          <Card border="solid" rounding="lg">
            <Section>
              <InputHorizontal
                title={t("admin.security.user_dir_visibility", "Full User Directory Visibility")}
                description={t("admin.security.user_dir_visibility_description", "Exact name and email lookups work regardless of this setting.")}
                withLabel
              >
                <div className="w-60">
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
                        description={t("admin.security.user_dir_visible_all_description", "Anyone signed in can see the full user list when sharing resources.")}
                      >
                        {t("admin.security.user_dir_visible_all", "Visible to All Users")}
                      </InputSelect.Item>
                      <InputSelect.Item
                        value="admins_only"
                        wrapDescription
                        description={t("admin.security.user_dir_admins_only_description", "Only admins can see the full user list.")}
                      >
                        {t("admin.security.user_dir_admins_only", "Visible to Admins Only")}
                      </InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelect>
                </div>
              </InputHorizontal>

              {!isMultiTenant && (
                <InputHorizontal
                  title={t("admin.security.mask_credentials", "Mask Stored Credentials")}
                  description={t("admin.security.mask_credentials_description", "Display format for saved API keys and credentials for admins.")}
                  withLabel
                >
                  <div className="w-60">
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
                          description={t("admin.security.credentials_partially_masked_description", "Show only the first and last few characters (e.g. abcd...wxyz).")}
                        >
                          {t("admin.security.credentials_partially_masked", "Partially Masked")}
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="visible"
                          wrapDescription
                          description={t("admin.security.credentials_fully_visible_description", "Show the full credential value to admins.")}
                        >
                          {t("admin.security.credentials_fully_visible", "Fully Visible")}
                        </InputSelect.Item>
                      </InputSelect.Content>
                    </InputSelect>
                  </div>
                </InputHorizontal>
              )}
            </Section>
          </Card>
        </div>

        {/* Network Safety (single-tenant only — SSRF policy is operator-controlled,
            so it stays env-driven in multi-tenant cloud). */}
        {!isMultiTenant && (
          <div className="flex w-full flex-col gap-3">
            <Content
              title={t("admin.security.network_safety", "Network Safety")}
              sizePreset="main-content"
              variant="section"
            />

            <Card border="solid" rounding="lg">
              <Section>
                <InputHorizontal
                  title={t("admin.security.ssrf_protection", "SSRF Protection")}
                  description={t("admin.security.ssrf_protection_description", "Validate outbound requests against private or internal IPs for Server-Side Request Forgery (SSRF) protection.")}
                  withLabel
                >
                  <div className="w-60">
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
                          description={t("admin.security.ssrf_validate_all_description", "Most restrictive. All outbound requests refuse to reach private or internal IPs, including web connectors.")}
                        >
                          {t("admin.security.ssrf_validate_all", "Validate All Requests")}
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="validate_llm"
                          wrapDescription
                          description={t("admin.security.ssrf_validate_llm_description", "Validate all LLM-initiated URL fetches. Admin-configured connectors can still reach private or internal IPs.")}
                        >
                          {t("admin.security.ssrf_validate_llm", "Validate LLM Requests")}
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="allow_private_network"
                          wrapDescription
                          description={t("admin.security.ssrf_allow_private_description", "Like Validate LLM Requests, but admin-configured MCP/OAuth endpoints may also reach private LAN hosts. Loopback (the app host itself) and cloud-metadata stay blocked.")}
                        >
                          {t("admin.security.ssrf_allow_private", "Allow Private Network")}
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="disabled"
                          wrapDescription
                          description={t("admin.security.ssrf_disabled_description", "Use only in trusted networks. Allow all outbound requests — required for connecting to local LLM backends.")}
                        >
                          {t("admin.security.ssrf_disabled", "Disabled")}
                        </InputSelect.Item>
                      </InputSelect.Content>
                    </InputSelect>
                  </div>
                </InputHorizontal>
              </Section>
            </Card>
          </div>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
