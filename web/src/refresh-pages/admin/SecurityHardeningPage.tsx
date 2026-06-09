"use client";

import React, { useCallback, useEffect, useState } from "react";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { Section } from "@/layouts/general-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { toast } from "@/hooks/useToast";
import InputNumber from "@/refresh-components/inputs/InputNumber";
import InputChipField, {
  type ChipItem,
} from "@/refresh-components/inputs/InputChipField";
import { InputHorizontal, InputVertical, SettingsLayouts } from "@opal/layouts";
import { Card, Divider, Switch, Text } from "@opal/components";

const route = ADMIN_ROUTES.SECURITY_HARDENING;

const SECURITY_SETTINGS_KEY = "/api/admin/security";

// Read shape: the effective, env-merged settings returned by GET /admin/security.
// Every field is concrete — the backend never returns null here (see
// `SecuritySettings` in backend/onyx/server/security/models.py).
interface SecuritySettings {
  user_directory_admin_only: boolean;
  track_external_idp_expiry: boolean;
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
  description: string;
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
  const isMultiTenant = NEXT_PUBLIC_CLOUD_ENABLED;

  const { data: settings, isLoading: settingsLoading } =
    useSWR<SecuritySettings>(SECURITY_SETTINGS_KEY, errorHandlingFetcher);

  // Local state mirrors the loaded settings; we save on every change.
  const [draft, setDraft] = useState<SecuritySettings | null>(null);
  const [domainInput, setDomainInput] = useState("");

  useEffect(() => {
    if (settings) setDraft(settings);
  }, [settings]);

  const saveSettings = useCallback(
    async (updates: SecuritySettingsUpdate) => {
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
        const response = await fetch(SECURITY_SETTINGS_KEY, {
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
        await mutate(SECURITY_SETTINGS_KEY, effective, { revalidate: false });
        toast.success("Security settings updated");
      } catch (error) {
        // Roll back the optimistic update to the last known-good settings.
        setDraft(settings ?? null);
        const message =
          error instanceof Error
            ? error.message
            : "Failed to update security settings";
        toast.error(message);
      }
    },
    [settings]
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
        description="Runtime-configurable security and hardening settings. Unset values fall back to your deployment's environment configuration."
        divider
      />

      <SettingsLayouts.Body>
        {/* Card 1 — Account & access */}
        <Card border="solid" rounding="lg">
          <Section>
            <ToggleRow
              title="Restrict User Directory to Admins"
              description="When enabled, only admins can list users in the workspace. Curators and basic users see only themselves."
              checked={draft.user_directory_admin_only}
              onCheckedChange={(checked) =>
                void saveSettings({ user_directory_admin_only: checked })
              }
            />

            <ToggleRow
              title="Track External IdP Session Expiry"
              description="Sync session expiration from your OAuth/OIDC provider. Users are logged out when the upstream session expires."
              checked={draft.track_external_idp_expiry}
              onCheckedChange={(checked) =>
                void saveSettings({ track_external_idp_expiry: checked })
              }
            />

            {!isMultiTenant && (
              <>
                <ToggleRow
                  title="Mask Credential Prefix"
                  description="Hide the leading characters of stored credentials when displayed in the UI."
                  checked={draft.mask_credential_prefix}
                  onCheckedChange={(checked) =>
                    void saveSettings({ mask_credential_prefix: checked })
                  }
                />

                <InputVertical
                  title="Allowed Email Domains"
                  subDescription="When set, only users with an email at one of these domains can register. Leave empty to allow any domain."
                  withLabel
                >
                  <InputChipField
                    chips={validDomains}
                    onRemoveChip={removeDomain}
                    onAdd={addDomain}
                    value={domainInput}
                    onChange={setDomainInput}
                    placeholder="Add a domain (e.g. onyx.app) and press Enter"
                  />
                </InputVertical>
              </>
            )}
          </Section>
        </Card>

        {/* Card 2 — Password policy (single-tenant only) */}
        {!isMultiTenant && (
          <>
            <Divider paddingParallel="fit" paddingPerpendicular="fit" />

            <Card border="solid" rounding="lg">
              <Section>
                <Text font="heading-h3" color="text-04">
                  Password Policy
                </Text>
                <div className="flex gap-4 w-full items-start pt-2">
                  <div className="flex-1">
                    <InputVertical title="Minimum Length" withLabel>
                      <InputNumber
                        value={draft.password_min_length}
                        onChange={(value) =>
                          void saveSettings({ password_min_length: value })
                        }
                        min={1}
                        max={1024}
                        placeholder="Default"
                      />
                    </InputVertical>
                  </div>
                  <div className="flex-1">
                    <InputVertical title="Maximum Length" withLabel>
                      <InputNumber
                        value={draft.password_max_length}
                        onChange={(value) =>
                          void saveSettings({ password_max_length: value })
                        }
                        min={1}
                        max={1024}
                        placeholder="Default"
                      />
                    </InputVertical>
                  </div>
                </div>

                <ToggleRow
                  title="Require Uppercase Letter"
                  description="Passwords must contain at least one uppercase character."
                  checked={draft.password_require_uppercase}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_uppercase: checked })
                  }
                />

                <ToggleRow
                  title="Require Lowercase Letter"
                  description="Passwords must contain at least one lowercase character."
                  checked={draft.password_require_lowercase}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_lowercase: checked })
                  }
                />

                <ToggleRow
                  title="Require Digit"
                  description="Passwords must contain at least one numeric digit."
                  checked={draft.password_require_digit}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_digit: checked })
                  }
                />

                <ToggleRow
                  title="Require Special Character"
                  description="Passwords must contain at least one special character."
                  checked={draft.password_require_special_char}
                  onCheckedChange={(checked) =>
                    void saveSettings({
                      password_require_special_char: checked,
                    })
                  }
                />
              </Section>
            </Card>
          </>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
