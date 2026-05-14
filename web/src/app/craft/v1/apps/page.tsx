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
  ExternalAppUserResponse,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";

interface OAuthStartResponse {
  authorize_url: string;
}

export default function ExternalAppsUserPage() {
  // keepPreviousData so revalidations don't blank the cards.
  const { data, mutate } = useSWR<ExternalAppUserResponse[]>(
    SWR_KEYS.buildExternalApps,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgPlug}
        title="My Apps"
        description="Connect your accounts so Onyx Craft can use them as context."
      />
      <SettingsLayouts.Body>
        {data === undefined ? (
          <Card variant="tertiary">
            <Text mainContentBody>Loading…</Text>
          </Card>
        ) : data.length === 0 ? (
          <Card variant="tertiary">
            <Text mainContentBody text03>
              No external apps are enabled for your org yet. Ask an admin to
              enable one.
            </Text>
          </Card>
        ) : (
          <div className="flex flex-col gap-2">
            {data.map((userApp) => (
              <ProviderConnectRow
                key={userApp.id}
                userApp={userApp}
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
  userApp: ExternalAppUserResponse;
  onChange: () => void;
}

function ProviderConnectRow({ userApp, onChange }: ProviderConnectRowProps) {
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
      window.location.href = data.authorize_url;
    } finally {
      setIsStarting(false);
    }
  }

  // Overwrite stored creds with `{}` — flips `authenticated` to false
  // on the next list call. Avoids a dedicated DELETE endpoint.
  async function disconnect() {
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

  const Logo = getAppTypeLogo(userApp.app_type);
  return (
    <Card>
      <div className="flex items-center gap-3 w-full">
        <Logo className="w-8 h-8" />
        <div className="flex-1 flex flex-col gap-0.5">
          <div className="flex items-center gap-2">
            <Text mainUiAction>{userApp.name}</Text>
            {userApp.authenticated && (
              <SvgCheckCircle className="w-4 h-4 text-status-success-05" />
            )}
          </div>
          <Text secondaryBody text03>
            {userApp.authenticated ? "Connected" : userApp.description}
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
