"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { SettingsLayouts } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { cn } from "@opal/utils";
import { Button, Text } from "@opal/components";
import Card from "@/refresh-components/cards/Card";
import { SvgPlug, SvgCheckCircle } from "@opal/icons";
import {
  ExternalAppUserResponse,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";
import {
  disconnectUserFromApp,
  startExternalAppOAuth,
} from "@/app/craft/services/externalAppsService";
import UserCredentialsModal from "@/app/craft/v1/apps/UserCredentialsModal";
import { toast } from "@/hooks/useToast";

export default function ExternalAppsUserPage() {
  // keepPreviousData so revalidations don't blank the cards.
  const { data, mutate } = useSWR<ExternalAppUserResponse[]>(
    SWR_KEYS.buildExternalApps,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );
  const connectSlug = useSearchParams().get("connect");

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
            <Text font="main-content-body">Loading…</Text>
          </Card>
        ) : data.length === 0 ? (
          <Card variant="tertiary">
            <Text font="main-content-body" color="text-03">
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
                highlight={
                  connectSlug === userApp.slug && !userApp.authenticated
                }
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
  highlight?: boolean;
  onChange: () => void;
}

function ProviderConnectRow({
  userApp,
  highlight,
  onChange,
}: ProviderConnectRowProps) {
  const [isStarting, setIsStarting] = useState(false);
  const [credModalOpen, setCredModalOpen] = useState(false);
  const rowRef = useRef<HTMLDivElement>(null);

  // Deep-link landing: scroll the targeted row into view and focus its
  // Connect button so Enter immediately triggers the flow.
  useEffect(() => {
    if (!highlight) return;
    const el = rowRef.current;
    if (!el) return;
    el.scrollIntoView({ block: "center" });
    el.querySelector<HTMLButtonElement>("button")?.focus();
  }, [highlight]);

  async function connect() {
    // Custom apps have no OAuth provider — collect the user's credentials
    // directly via a popup instead of redirecting to an authorize URL.
    if (userApp.app_type === "CUSTOM") {
      setCredModalOpen(true);
      return;
    }
    setIsStarting(true);
    try {
      const { authorize_url } = await startExternalAppOAuth(userApp.id);
      window.location.href = authorize_url;
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Failed to start authorization"
      );
      setIsStarting(false);
    }
  }

  // Overwrite stored creds with `{}` — flips `authenticated` to false
  // on the next list call. Avoids a dedicated DELETE endpoint.
  async function disconnect() {
    setIsStarting(true);
    try {
      await disconnectUserFromApp(userApp.id);
      onChange();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to disconnect");
    } finally {
      setIsStarting(false);
    }
  }

  const Logo = getAppTypeLogo(userApp.app_type);
  const connectLabel =
    userApp.app_type === "CUSTOM"
      ? "Connect"
      : isStarting
        ? "Redirecting…"
        : "Connect";
  return (
    <>
      <div
        ref={rowRef}
        className={cn(
          "rounded-12 transition-shadow",
          highlight && "ring-2 ring-action-link-04"
        )}
      >
        <Card>
          <div className="flex items-center gap-3 w-full">
            <Logo className="w-8 h-8" />
            <div className="flex-1 flex flex-col gap-0.5">
              <div className="flex items-center gap-2">
                <Text font="main-ui-action">{userApp.name}</Text>
                {userApp.authenticated && (
                  <SvgCheckCircle className="w-4 h-4 text-status-success-05" />
                )}
              </div>
              <Text font="secondary-body" color="text-03">
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
                {connectLabel}
              </Button>
            )}
          </div>
        </Card>
      </div>

      <UserCredentialsModal
        open={credModalOpen}
        onClose={() => setCredModalOpen(false)}
        onSaved={onChange}
        userApp={userApp}
      />
    </>
  );
}
