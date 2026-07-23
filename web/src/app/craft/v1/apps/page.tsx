"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import useOnMount from "@/hooks/useOnMount";
import { cn } from "@opal/utils";
import { Button, Card, InputTypeIn, Text } from "@opal/components";
import { SettingsLayouts, toast } from "@opal/layouts";
import { SvgCheckCircle, SvgPlug, SvgSettings } from "@opal/icons";
import { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";
import { MCPServersResponse } from "@/lib/tools/interfaces";
import {
  ConnectableApp,
  externalAppToConnectable,
  mcpServerToConnectable,
} from "@/app/craft/v1/apps/connectableApps";
import UserCredentialsModal from "@/app/craft/v1/apps/UserCredentialsModal";
import { useUser } from "@/providers/UserProvider";

// The user's own app connections. Org-wide configuration lives in the admin
// panel's Craft section; admins get a shortcut button to it here.
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
            <Button
              href="/admin/craft/apps"
              prominence="secondary"
              icon={SvgSettings}
            >
              Manage apps
            </Button>
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
  const { data: externalApps, mutate: mutateApps } = useSWR<
    ExternalAppUserResponse[]
  >(SWR_KEYS.buildExternalApps, errorHandlingFetcher, {
    keepPreviousData: true,
  });
  const { data: mcpData, mutate: mutateMcp } = useSWR<MCPServersResponse>(
    SWR_KEYS.mcpServersCraft,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );
  const connectParam = useSearchParams().get("connect");

  const refresh = () => {
    void mutateApps();
    void mutateMcp();
  };

  const { connected, browse, isLoading, isEmpty } = useMemo(() => {
    const items = [
      ...(externalApps ?? []).map(externalAppToConnectable),
      ...(mcpData?.mcp_servers ?? [])
        .map(mcpServerToConnectable)
        .filter((item): item is ConnectableApp => item !== null),
    ].sort((a, b) => a.name.localeCompare(b.name));
    const q = query.trim().toLowerCase();
    const filtered = items.filter((item) =>
      q ? item.name.toLowerCase().includes(q) : true
    );
    return {
      connected: filtered.filter((item) => item.authenticated),
      browse: filtered.filter((item) => !item.authenticated),
      isLoading: externalApps === undefined && mcpData === undefined,
      isEmpty: items.length === 0,
    };
  }, [externalApps, mcpData, query]);

  if (isLoading) {
    return (
      <Card background="none" border="dashed" rounding="lg">
        <Text font="main-content-body">Loading…</Text>
      </Card>
    );
  }

  if (isEmpty) {
    return (
      <Card background="none" border="dashed" rounding="lg">
        <Text font="main-content-body" color="text-03">
          No external apps are configured for your organization yet.
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
            {connected.map((item) => (
              <ProviderConnectCard
                key={item.key}
                variant="row"
                app={item}
                onChange={refresh}
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
            {browse.map((item) => (
              <ProviderConnectCard
                key={item.key}
                variant="tile"
                app={item}
                highlight={
                  connectParam !== null && connectParam === item.connectId
                }
                onChange={refresh}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

interface ProviderConnectCardProps {
  app: ConnectableApp;
  variant: "row" | "tile";
  highlight?: boolean;
  onChange: () => void;
}

function ProviderConnectCard({
  app,
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
    if (app.connectMode === "credentials") {
      setCredModalOpen(true);
      return;
    }
    setIsStarting(true);
    try {
      window.location.href = await app.startOAuth();
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Failed to start authorization"
      );
      setIsStarting(false);
    }
  }

  async function disconnect() {
    if (!app.disconnect) return;
    setIsStarting(true);
    try {
      await app.disconnect();
      onChange();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to disconnect");
    } finally {
      setIsStarting(false);
    }
  }

  const Logo = app.logo;

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
                  <Text font="main-ui-action">{app.name}</Text>
                  <SvgCheckCircle className="w-4 h-4 text-status-success-05" />
                </div>
                <Text font="secondary-body" color="text-03">
                  Connected
                </Text>
              </div>
              {app.disconnect && (
                <Button
                  prominence="secondary"
                  disabled={isStarting}
                  onClick={disconnect}
                >
                  {isStarting ? "…" : "Disconnect"}
                </Button>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-3 w-full">
              <div className="flex items-center gap-3">
                <Logo className="w-8 h-8" />
                <Text font="main-ui-action">{app.name}</Text>
              </div>
              <Text font="secondary-body" color="text-03">
                {app.description}
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
        name={app.name}
        logo={app.logo}
        credentialKeys={app.credentialKeys}
        credentialValues={app.credentialValues}
        save={app.saveCredentials}
      />
    </>
  );
}
