"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
import type { RichStr } from "@opal/types";
import type {
  IncognitoAvailability,
  IncognitoRecordMode,
  SecuritySettings,
  SSRFProtectionLevel,
} from "@/lib/types";

const route = ADMIN_ROUTES.SECURITY_HARDENING;

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
        description="Pinned by an environment variable."
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
  const isMultiTenant = NEXT_PUBLIC_CLOUD_ENABLED;
  const { authTypeMetadata, isLoading: authTypeLoading } =
    useAuthTypeMetadata();
  // The kill switch only enforces on single-tenant deployments, so the
  // card hides where the backend would refuse the save. The explicit === false
  // waits for the fetch, metadata is undefined while loading or unreachable.
  const showPasswordLockdown =
    !isMultiTenant &&
    !authTypeLoading &&
    authTypeMetadata?.multiTenant === false;

  const { data: settings, isLoading: settingsLoading } =
    useSWR<SecuritySettings>(
      SWR_KEYS.adminSecuritySettings,
      errorHandlingFetcher
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

  const doSave = useCallback(async (updates: SecuritySettingsUpdate) => {
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
      toast.success("Security settings updated");
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
          : "Failed to update security settings";
      toast.error(message);
    }
  }, []);

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
        description="Runtime-configurable security settings. Unset values fall back to your deployment's environment configuration."
        divider
      />

      <SettingsLayouts.Body>
        {/* Authentication */}
        <div className="flex w-full flex-col gap-3">
          <Content
            title="Authentication"
            sizePreset="main-content"
            variant="section"
          />

          <Card border="solid" rounding="lg">
            <Section>
              <ToggleRow
                title="Sync Session Expiry with Identity Provider"
                description="Log users out when the upstream OAuth/OIDC provider session expires."
                checked={draft.track_external_idp_expiry}
                onCheckedChange={(checked) =>
                  void saveSettings({ track_external_idp_expiry: checked })
                }
              />

              {!isMultiTenant && (
                <>
                  <ToggleRow
                    title="Restrict Email Domains"
                    description="Limit new user registrations to specific email domains."
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
                      title="Allowed Email Domains"
                      subDescription="New users can only register new accounts with emails in this domain list."
                      withLabel
                    >
                      <InputChipField
                        chips={validDomains}
                        onRemoveChip={removeDomain}
                        onAdd={addDomain}
                        value={domainInput}
                        onChange={setDomainInput}
                        placeholder="Add a domain (e.g. onyx.app)"
                      />
                    </InputVertical>
                  )}
                </>
              )}

              {showPasswordLockdown && (
                <ToggleRow
                  title="Disable Password Login & Signup"
                  description="Everyone signs in and registers through SSO only. Requires at least one enabled SSO provider."
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
            <Card border="solid" rounding="lg">
              <Section>
                <Content
                  title="Password Policy"
                  description="Requirements for all new passwords. Applies to basic auth only."
                  sizePreset="main-ui"
                  variant="section"
                />

                <div className="flex w-full items-start gap-4">
                  <div className="flex-1">
                    <InputVertical
                      title="Minimum Password Length"
                      suffix="(characters)"
                      withLabel
                    >
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
                    <InputVertical
                      title="Maximum Password Length"
                      suffix="(characters)"
                      withLabel
                    >
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
                  checked={draft.password_require_uppercase}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_uppercase: checked })
                  }
                />

                <ToggleRow
                  title="Require Lowercase Letter"
                  checked={draft.password_require_lowercase}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_lowercase: checked })
                  }
                />

                <ToggleRow
                  title="Require Number"
                  checked={draft.password_require_digit}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_digit: checked })
                  }
                />

                <ToggleRow
                  title="Require Special Characters"
                  description={markdown(
                    "Accepted characters: `!@#$%^&*()_+-=[]{}|;:,.<>?`"
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
            <Card border="solid" rounding="lg">
              <Section>
                <Content
                  title="External JWT Authentication"
                  description="Accept RS256 bearer tokens signed by your identity provider. Values set by environment variables are pinned and cannot be edited here."
                  sizePreset="main-ui"
                  variant="section"
                />

                <JwtTextRow
                  title="Public Key URL"
                  description="JWKS or PEM endpoint used to verify token signatures. Leave empty to disable JWT authentication."
                  value={draft.jwt_public_key_url ?? ""}
                  placeholder="https://idp.example.com/.well-known/jwks.json"
                  pinned={pinnedFields.includes("jwt_public_key_url")}
                  onCommit={(value) =>
                    saveSettings({ jwt_public_key_url: value || null })
                  }
                />

                <JwtTextRow
                  title="Expected Audience"
                  description="Reject tokens whose aud claim does not match. Empty disables the check."
                  value={draft.jwt_expected_audience ?? ""}
                  placeholder="onyx"
                  pinned={pinnedFields.includes("jwt_expected_audience")}
                  onCommit={(value) =>
                    saveSettings({ jwt_expected_audience: value || null })
                  }
                />

                <JwtTextRow
                  title="Expected Issuer"
                  description="Reject tokens whose iss claim does not match. Empty disables the check."
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
            title="Admin Controls"
            sizePreset="main-content"
            variant="section"
          />

          <Card border="solid" rounding="lg">
            <Section>
              <InputHorizontal
                title="Full User Directory Visibility"
                description="Exact name and email lookups work regardless of this setting."
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
                        description="Anyone signed in can see the full user list when sharing resources."
                      >
                        Visible to All Users
                      </InputSelect.Item>
                      <InputSelect.Item
                        value="admins_only"
                        wrapDescription
                        description="Only admins can see the full user list."
                      >
                        Visible to Admins Only
                      </InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelect>
                </div>
              </InputHorizontal>

              <InputHorizontal
                title="Incognito Chats"
                description="Incognito chats never appear in their owner's history. Group access is configured per group under Groups."
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
                        description="No one can start incognito chats."
                      >
                        Off
                      </InputSelect.Item>
                      <InputSelect.Item
                        value="everyone"
                        wrapDescription
                        description="Anyone signed in can start incognito chats."
                      >
                        Everyone
                      </InputSelect.Item>
                      <InputSelect.Item
                        value="groups"
                        wrapDescription
                        description="Only members of groups with incognito access enabled."
                      >
                        Designated Groups
                      </InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelect>
                </div>
              </InputHorizontal>

              <InputHorizontal
                title="Incognito Chat Records"
                description="What the workspace keeps from incognito chats. New sessions pin the mode active when they start."
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
                        description="No message content is stored. Token usage is still tracked, and these chats do not appear in query history."
                      >
                        Usage Only
                      </InputSelect.Item>
                      <InputSelect.Item
                        value="full_history"
                        wrapDescription
                        description="Recorded like any other chat: query history, usage, and tracing. Hidden only from the owner's own history."
                      >
                        Full History
                      </InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelect>
                </div>
              </InputHorizontal>

              {!isMultiTenant && (
                <InputHorizontal
                  title="Mask Stored Credentials"
                  description="Display format for saved API keys and credentials for admins."
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
                          description="Show only the first and last few characters (e.g. abcd...wxyz)."
                        >
                          Partially Masked
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="visible"
                          wrapDescription
                          description="Show the full credential value to admins."
                        >
                          Fully Visible
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
            title="Network Safety"
            sizePreset="main-content"
            variant="section"
          />

          <Card border="solid" rounding="lg">
            <Section>
              <ToggleRow
                title="LLM Environment Variable Injection"
                description={
                  isMultiTenant
                    ? "Custom LLM provider configurations can never set process environment variables on multi-tenant deployments."
                    : "Allow custom LLM provider configurations to temporarily set process environment variables during calls. Disable to require all provider settings to have a LiteLLM parameter equivalent."
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
                  title="SSRF Protection"
                  description="Validate outbound requests against private or internal IPs for Server-Side Request Forgery (SSRF) protection."
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
                          description="Most restrictive. All outbound requests refuse to reach private or internal IPs, including web connectors."
                        >
                          Validate All Requests
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="validate_llm"
                          wrapDescription
                          description="Validate all LLM-initiated URL fetches. Admin-configured connectors can still reach private or internal IPs."
                        >
                          Validate LLM Requests
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="allow_private_network"
                          wrapDescription
                          description="Like Validate LLM Requests, but admin-configured MCP/OAuth endpoints may also reach private LAN hosts. Loopback (the app host itself) and cloud-metadata stay blocked."
                        >
                          Allow Private Network
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="disabled"
                          wrapDescription
                          description="Use only in trusted networks. Allow all outbound requests — required for connecting to local LLM backends."
                        >
                          Disabled
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
