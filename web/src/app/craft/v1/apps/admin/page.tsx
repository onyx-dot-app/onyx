"use client";

import { useState } from "react";
import useSWR from "swr";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Button } from "@opal/components";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import { SvgPlug } from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
import {
  BUILT_IN_PROVIDER_REGISTRY,
  BuiltInProviderKey,
  BuiltInProviderPreset,
  ExternalAppAdminResponse,
  findAppForProvider,
} from "@/app/craft/v1/apps/registry";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";

export default function ExternalAppsAdminPage() {
  const { isAdmin } = useUser();
  const { data, isLoading, mutate } = useSWR<ExternalAppAdminResponse[]>(
    SWR_KEYS.buildExternalAppsAdmin,
    errorHandlingFetcher
  );
  const apps = data ?? [];

  if (!isAdmin) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={SvgPlug}
          title="External Apps"
          description="Admin access required to manage org-wide external apps."
        />
      </SettingsLayouts.Root>
    );
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgPlug}
        title="External Apps"
        description="Enable third-party integrations that users in your org can connect their personal accounts to."
      />
      <SettingsLayouts.Body>
        {isLoading ? (
          <Card variant="tertiary">
            <Text mainContentBody>Loading…</Text>
          </Card>
        ) : (
          <div className="flex flex-col gap-2">
            {Object.entries(BUILT_IN_PROVIDER_REGISTRY).map(([key, preset]) => (
              <ProviderRow
                key={key}
                providerKey={key as BuiltInProviderKey}
                preset={preset}
                existingApp={findAppForProvider(
                  apps,
                  key as BuiltInProviderKey
                )}
                onChange={() => mutate()}
              />
            ))}
          </div>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

interface ProviderRowProps {
  providerKey: BuiltInProviderKey;
  preset: BuiltInProviderPreset;
  existingApp: ExternalAppAdminResponse | null;
  onChange: () => void;
}

function ProviderRow({ preset, existingApp, onChange }: ProviderRowProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const [isMutating, setIsMutating] = useState(false);

  const hasCredentials =
    existingApp !== null &&
    preset.required_org_credential_fields.every(
      (f) => (existingApp.organization_credentials[f.key] ?? "").length > 0
    );
  const enabled = existingApp?.enabled ?? false;

  /**
   * Toggle `enabled` on an existing row without touching credentials.
   * Used by the Enable/Disable buttons; the Configure modal handles
   * credential edits separately.
   */
  async function setEnabled(nextEnabled: boolean) {
    if (!existingApp) return;
    setIsMutating(true);
    try {
      const body = {
        id: existingApp.id,
        name: existingApp.name,
        description: existingApp.description,
        upstream_urls: existingApp.upstream_urls,
        auth_template: existingApp.auth_template,
        organization_credentials: existingApp.organization_credentials,
        enabled: nextEnabled,
      };
      const res = await fetch("/api/build/admin/apps", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        console.error("Failed to update enabled state:", await res.text());
      }
      onChange();
    } finally {
      setIsMutating(false);
    }
  }

  const Logo = preset.logo;

  // Three rendering states, in order of "needs admin attention":
  //  1. Not configured at all → only the Configure button.
  //  2. Configured but disabled → Edit credentials + Enable.
  //  3. Configured and enabled → Edit credentials + Disable.
  // Splitting Configure (creds) from Enable/Disable (toggle) means
  // admins can pause a provider without losing the client_id/secret
  // they typed in.
  let statusLine: string;
  let rightSide: React.ReactNode;
  if (!hasCredentials) {
    statusLine = preset.description;
    rightSide = (
      <Button onClick={() => setModalOpen(true)} disabled={isMutating}>
        Configure
      </Button>
    );
  } else if (!enabled) {
    statusLine = "Configured · disabled";
    rightSide = (
      <div className="flex items-center gap-2">
        <Button
          prominence="secondary"
          onClick={() => setModalOpen(true)}
          disabled={isMutating}
        >
          Edit credentials
        </Button>
        <Button onClick={() => setEnabled(true)} disabled={isMutating}>
          {isMutating ? "…" : "Enable"}
        </Button>
      </div>
    );
  } else {
    statusLine = "Enabled";
    rightSide = (
      <div className="flex items-center gap-2">
        <Button
          prominence="secondary"
          onClick={() => setModalOpen(true)}
          disabled={isMutating}
        >
          Edit credentials
        </Button>
        <Button
          prominence="secondary"
          onClick={() => setEnabled(false)}
          disabled={isMutating}
        >
          {isMutating ? "…" : "Disable"}
        </Button>
      </div>
    );
  }

  return (
    <>
      <Card>
        <div className="flex items-center gap-3 w-full">
          <Logo className="w-8 h-8" />
          <div className="flex-1 flex flex-col gap-0.5">
            <Text mainUiAction>{preset.name}</Text>
            <Text secondaryBody text03>
              {statusLine}
            </Text>
          </div>
          {rightSide}
        </div>
      </Card>
      <ConfigureProviderModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={onChange}
        preset={preset}
        existingApp={existingApp}
      />
    </>
  );
}
