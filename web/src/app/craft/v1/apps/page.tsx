"use client";

import { useState } from "react";
import useSWR from "swr";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Button } from "@opal/components";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import { SvgPlug, SvgCheckCircle } from "@opal/icons";
import {
  BUILT_IN_PROVIDER_REGISTRY,
  BuiltInProviderKey,
  ExternalAppUserResponse,
  findUserAppForProvider,
} from "@/app/craft/v1/apps/registry";

interface OAuthStartResponse {
  authorize_url: string;
}

export default function ExternalAppsUserPage() {
  const { data, isLoading, mutate } = useSWR<ExternalAppUserResponse[]>(
    SWR_KEYS.buildExternalApps,
    errorHandlingFetcher
  );
  const apps = data ?? [];

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgPlug}
        title="My Apps"
        description="Connect your accounts so Onyx Craft can use them as context."
      />
      <SettingsLayouts.Body>
        {isLoading ? (
          <Card variant="tertiary">
            <Text mainContentBody>Loading…</Text>
          </Card>
        ) : apps.length === 0 ? (
          <Card variant="tertiary">
            <Text mainContentBody text03>
              No external apps are enabled for your org yet. Ask an admin to
              enable one.
            </Text>
          </Card>
        ) : (
          <div className="flex flex-col gap-2">
            {(Object.keys(BUILT_IN_PROVIDER_REGISTRY) as BuiltInProviderKey[])
              .map((key) => ({
                key,
                preset: BUILT_IN_PROVIDER_REGISTRY[key],
                userApp: findUserAppForProvider(apps, key),
              }))
              .filter(({ userApp }) => userApp !== null)
              .map(({ key, preset, userApp }) => (
                <ProviderConnectRow
                  key={key}
                  preset={preset}
                  userApp={userApp!}
                  onChange={() => mutate()}
                />
              ))}
          </div>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

interface ProviderConnectRowProps {
  preset: (typeof BUILT_IN_PROVIDER_REGISTRY)[BuiltInProviderKey];
  userApp: ExternalAppUserResponse;
  onChange: () => void;
}

function ProviderConnectRow({
  preset,
  userApp,
  onChange,
}: ProviderConnectRowProps) {
  const [isStarting, setIsStarting] = useState(false);

  async function connect() {
    setIsStarting(true);
    try {
      const res = await fetch(`/api/build/apps/${userApp.id}/oauth/start`, {
        method: "GET",
      });
      if (!res.ok) {
        console.error("Failed to start OAuth:", await res.text());
        return;
      }
      const data: OAuthStartResponse = await res.json();
      // Full-page navigation so the OAuth provider can redirect back to
      // the callback page. A popup approach is also valid but adds
      // postMessage plumbing — full-page is simpler for v1.
      window.location.href = data.authorize_url;
    } finally {
      setIsStarting(false);
    }
  }

  async function disconnect() {
    // "Disconnect" = overwrite stored creds with an empty dict, which
    // flips `authenticated` back to false on the next list call. A
    // dedicated DELETE endpoint would be cleaner; reusing the upsert
    // route keeps the API surface tight for v1.
    setIsStarting(true);
    try {
      const res = await fetch(`/api/build/apps/${userApp.id}/credentials`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_credentials: {} }),
      });
      if (!res.ok) {
        console.error("Failed to disconnect:", await res.text());
      }
      onChange();
    } finally {
      setIsStarting(false);
    }
  }

  const Logo = preset.logo;
  return (
    <Card>
      <div className="flex items-center gap-3 w-full">
        <Logo className="w-8 h-8" />
        <div className="flex-1 flex flex-col gap-0.5">
          <div className="flex items-center gap-2">
            <Text mainUiAction>{preset.name}</Text>
            {userApp.authenticated && (
              <SvgCheckCircle className="w-4 h-4 text-status-success-05" />
            )}
          </div>
          <Text secondaryBody text03>
            {userApp.authenticated ? "Connected" : preset.description}
          </Text>
        </div>
        {userApp.authenticated ? (
          <Button
            prominence="secondary"
            disabled={isStarting}
            onClick={disconnect}
          >
            {isStarting ? "…" : "Disconnect"}
          </Button>
        ) : (
          <Button disabled={isStarting} onClick={connect}>
            {isStarting ? "Redirecting…" : "Connect"}
          </Button>
        )}
      </div>
    </Card>
  );
}
