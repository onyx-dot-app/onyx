"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import useOnMount from "@/hooks/useOnMount";
import { cn } from "@opal/utils";
import { Button, Card, InputTypeIn, Text } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import { SvgCheckCircle, SvgPlug, SvgSettings } from "@opal/icons";
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
import { useUser } from "@/providers/UserProvider";

// The user's own app connections. Org-wide configuration lives at
// /craft/v1/apps/manage (admin-only); admins get a shortcut button to it here.
export default function ExternalAppsPage() {
  const { isAdmin } = useUser();
  const [query, setQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);
  // A `?connect` deep-link focuses the targeted card's Connect button, so don't
  // steal that focus by autofocusing the search.
  const hasConnectDeepLink = useSearchParams().has("connect");

  useOnMount(() => {
    if (!hasConnectDeepLink) searchInputRef.current?.focus();
  });

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgPlug}
        title="Apps"
        description="Connect the tools Onyx Craft can use as context while it works."
        rightChildren={
          isAdmin ? (
            <div className="flex items-center gap-2">
              <Button
                href="/craft/v1/apps/manage"
                prominence="secondary"
                icon={SvgSettings}
              >
                Manage apps
              </Button>
            </div>
          ) : undefined
        }
      >
        <InputTypeIn
          ref={searchInputRef}
          placeholder="Search apps..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          searchIcon
        />
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>
        <AppConnections query={query} />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

interface AppConnectionsProps {
  query: string;
}

function AppConnections({ query }: AppConnectionsProps) {
  const { data, mutate } = useSWR<ExternalAppUserResponse[]>(
    SWR_KEYS.buildExternalApps,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );
  const connectSlug = useSearchParams().get("connect");

  const { connected, browse } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = (data ?? []).filter((app) =>
      q ? app.name.toLowerCase().includes(q) : true
    );
    return {
      connected: filtered.filter((app) => app.authenticated),
      browse: filtered.filter((app) => !app.authenticated),
    };
  }, [data, query]);

  if (data === undefined) {
    return (
      <Card background="none" border="dashed" rounding="lg">
        <Text font="main-content-body">Loading…</Text>
      </Card>
    );
  }

  if (data.length === 0) {
    return (
      <Card background="none" border="dashed" rounding="lg">
        <Text font="main-content-body" color="text-03">
          No external apps are enabled for your org yet. Ask an admin to enable
          one.
        </Text>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {connected.length > 0 && (
        <section className="flex flex-col gap-2">
          <Text font="secondary-body" color="text-03">
            Connected
          </Text>
          <div className="flex flex-col gap-2">
            {connected.map((userApp) => (
              <ProviderConnectCard
                key={userApp.id}
                variant="row"
                userApp={userApp}
                onChange={() => mutate()}
              />
            ))}
          </div>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <Text font="secondary-body" color="text-03">
          Browse apps
        </Text>
        {browse.length === 0 ? (
          <Text font="secondary-body" color="text-03">
            {query ? "No apps match your search." : "Everything is connected."}
          </Text>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {browse.map((userApp) => (
              <ProviderConnectCard
                key={userApp.id}
                variant="tile"
                userApp={userApp}
                highlight={connectSlug === userApp.slug}
                onChange={() => mutate()}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

interface ProviderConnectCardProps {
  userApp: ExternalAppUserResponse;
  variant: "row" | "tile";
  highlight?: boolean;
  onChange: () => void;
}

function ProviderConnectCard({
  userApp,
  variant,
  highlight,
  onChange,
}: ProviderConnectCardProps) {
  const [isStarting, setIsStarting] = useState(false);
  const [credModalOpen, setCredModalOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Deep-link landing: scroll the targeted card into view and focus its
  // Connect button so Enter immediately triggers the flow.
  useEffect(() => {
    if (!highlight) return;
    const el = rootRef.current;
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

  return (
    <>
      <div
        ref={rootRef}
        className={cn(
          "rounded-12 transition-shadow",
          highlight && "ring-2 ring-action-link-04"
        )}
      >
        <Card background="light" border="solid" rounding="lg">
          {variant === "row" ? (
            <div className="flex items-center gap-3 w-full">
              <Logo className="w-8 h-8" />
              <div className="flex-1 flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <Text font="main-ui-action">{userApp.name}</Text>
                  <SvgCheckCircle className="w-4 h-4 text-status-success-05" />
                </div>
                <Text font="secondary-body" color="text-03">
                  Connected
                </Text>
              </div>
              <Button
                prominence="secondary"
                disabled={isStarting}
                onClick={disconnect}
              >
                {isStarting ? "…" : "Disconnect"}
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-3 w-full">
              <div className="flex items-center gap-3">
                <Logo className="w-8 h-8" />
                <Text font="main-ui-action">{userApp.name}</Text>
              </div>
              <Text font="secondary-body" color="text-03">
                {userApp.description}
              </Text>
              <Button disabled={isStarting} onClick={connect}>
                {isStarting ? "Redirecting…" : "Connect"}
              </Button>
            </div>
          )}
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
