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
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
  findAppForType,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";

export default function ExternalAppsAdminPage() {
  const { isAdmin } = useUser();

  // keepPreviousData so revalidations don't blank the cards.
  const { data: descriptors } = useSWR<BuiltInExternalAppDescriptor[]>(
    SWR_KEYS.buildExternalAppsBuiltInOptions,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );
  const { data: apps, mutate: mutateApps } = useSWR<ExternalAppAdminResponse[]>(
    SWR_KEYS.buildExternalAppsAdmin,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );

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

  const isReady = descriptors !== undefined && apps !== undefined;

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgPlug}
        title="External Apps"
        description="Enable third-party integrations that users in your org can connect their personal accounts to."
      />
      <SettingsLayouts.Body>
        {!isReady ? (
          <Card variant="tertiary">
            <Text mainContentBody>Loading…</Text>
          </Card>
        ) : (
          <div className="flex flex-col gap-2">
            {descriptors.map((descriptor) => (
              <ProviderRow
                key={descriptor.app_type}
                descriptor={descriptor}
                existingApp={findAppForType(apps, descriptor.app_type)}
                onChange={() => mutateApps()}
              />
            ))}
          </div>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

interface ProviderRowProps {
  descriptor: BuiltInExternalAppDescriptor;
  existingApp: ExternalAppAdminResponse | null;
  onChange: () => void;
}

function ProviderRow({ descriptor, existingApp, onChange }: ProviderRowProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const [isMutating, setIsMutating] = useState(false);

  const hasCredentials =
    existingApp !== null &&
    descriptor.required_org_credential_fields.every(
      (f) => (existingApp.organization_credentials[f.key] ?? "").length > 0
    );
  const enabled = existingApp?.enabled ?? false;

  // Enable/Disable toggle preserves credentials — separate from the
  // Configure modal which edits creds.
  async function setEnabled(nextEnabled: boolean) {
    if (!existingApp) return;
    setIsMutating(true);
    try {
      const body = {
        id: existingApp.id,
        name: existingApp.name,
        description: existingApp.description,
        app_type: existingApp.app_type,
        upstream_url_patterns: existingApp.upstream_url_patterns,
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

  const Logo = getAppTypeLogo(descriptor.app_type);

  let statusLine: string;
  let rightSide: React.ReactNode;
  if (!hasCredentials) {
    statusLine = descriptor.description;
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
            <Text mainUiAction>{descriptor.name}</Text>
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
        descriptor={descriptor}
        existingApp={existingApp}
      />
    </>
  );
}
