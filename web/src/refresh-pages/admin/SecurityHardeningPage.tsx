"use client";

import { useCallback, useEffect, useState } from "react";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
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
      toast.success("安全设置已更新");
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
          : "更新安全设置失败";
      toast.error(message);
    }
  }, []);

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
        description="运行时可配置的安全设置。未设置的值会回退到部署环境配置。"
        divider
      />

      <SettingsLayouts.Body>
        {/* Authentication */}
        <div className="flex w-full flex-col gap-3">
          <Content
            title="身份认证"
            sizePreset="main-content"
            variant="section"
          />

          <Card border="solid" rounding="lg">
            <Section>
              <ToggleRow
                title="同步身份提供商会话过期时间"
                description="当上游 OAuth/OIDC 提供商会话过期时，自动让用户退出登录。"
                checked={draft.track_external_idp_expiry}
                onCheckedChange={(checked) =>
                  void saveSettings({ track_external_idp_expiry: checked })
                }
              />

              {!isMultiTenant && (
                <>
                  <ToggleRow
                    title="限制邮箱域名"
                    description="仅允许指定邮箱域名的新用户注册。"
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
                      title="允许的邮箱域名"
                      subDescription="新用户只能使用此域名列表中的邮箱注册账号。"
                      withLabel
                    >
                      <InputChipField
                        chips={validDomains}
                        onRemoveChip={removeDomain}
                        onAdd={addDomain}
                        value={domainInput}
                        onChange={setDomainInput}
                        placeholder="添加域名（例如 glomi.ai）"
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
                  title="密码策略"
                  description="所有新密码的要求。仅适用于基础认证。"
                  sizePreset="main-ui"
                  variant="section"
                />

                <div className="flex w-full items-start gap-4">
                  <div className="flex-1">
                    <InputVertical
                      title="最小密码长度"
                      suffix="（字符）"
                      withLabel
                    >
                      <InputNumber
                        value={draft.password_min_length}
                        onChange={(value) =>
                          void saveSettings({ password_min_length: value })
                        }
                        min={1}
                        max={1024}
                        placeholder="默认"
                      />
                    </InputVertical>
                  </div>
                  <div className="flex-1">
                    <InputVertical
                      title="最大密码长度"
                      suffix="（字符）"
                      withLabel
                    >
                      <InputNumber
                        value={draft.password_max_length}
                        onChange={(value) =>
                          void saveSettings({ password_max_length: value })
                        }
                        min={1}
                        max={1024}
                        placeholder="默认"
                      />
                    </InputVertical>
                  </div>
                </div>

                <ToggleRow
                  title="要求包含大写字母"
                  checked={draft.password_require_uppercase}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_uppercase: checked })
                  }
                />

                <ToggleRow
                  title="要求包含小写字母"
                  checked={draft.password_require_lowercase}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_lowercase: checked })
                  }
                />

                <ToggleRow
                  title="要求包含数字"
                  checked={draft.password_require_digit}
                  onCheckedChange={(checked) =>
                    void saveSettings({ password_require_digit: checked })
                  }
                />

                <ToggleRow
                  title="要求包含特殊字符"
                  description={markdown(
                    "可用字符：`!@#$%^&*()_+-=[]{}|;:,.<>?`"
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
            title="管理员控制"
            sizePreset="main-content"
            variant="section"
          />

          <Card border="solid" rounding="lg">
            <Section>
              <InputHorizontal
                title="完整用户目录可见性"
                description="精确姓名和邮箱查找不受此设置影响。"
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
                        description="任何已登录用户在共享资源时都可以看到完整用户列表。"
                      >
                        对所有用户可见
                      </InputSelect.Item>
                      <InputSelect.Item
                        value="admins_only"
                        wrapDescription
                        description="只有管理员可以看到完整用户列表。"
                      >
                        仅管理员可见
                      </InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelect>
                </div>
              </InputHorizontal>

              {!isMultiTenant && (
                <InputHorizontal
                  title="隐藏已存储凭据"
                  description="管理员查看已保存 API Key 和凭据时的显示格式。"
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
                          description="仅显示开头和结尾的少量字符（例如 abcd...wxyz）。"
                        >
                          部分隐藏
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="visible"
                          wrapDescription
                          description="向管理员显示完整凭据值。"
                        >
                          完整可见
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
              title="网络安全"
              sizePreset="main-content"
              variant="section"
            />

            <Card border="solid" rounding="lg">
              <Section>
                <InputHorizontal
                  title="SSRF 防护"
                  description="校验外发请求是否访问私有或内部 IP，用于防范服务端请求伪造（SSRF）。"
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
                          description="最严格。所有外发请求都拒绝访问私有或内部 IP，包括网页连接器。"
                        >
                          校验所有请求
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="validate_llm"
                          wrapDescription
                          description="校验所有由 LLM 发起的 URL 抓取。管理员配置的连接器仍可访问私有或内部 IP。"
                        >
                          校验 LLM 请求
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="allow_private_network"
                          wrapDescription
                          description="类似“校验 LLM 请求”，但管理员配置的 MCP/OAuth 端点也可以访问私有局域网主机。回环地址（应用所在主机）和云元数据仍会被阻止。"
                        >
                          允许私有网络
                        </InputSelect.Item>
                        <InputSelect.Item
                          value="disabled"
                          wrapDescription
                          description="仅在可信网络中使用。允许所有外发请求，连接本地 LLM 后端时需要此选项。"
                        >
                          已禁用
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
