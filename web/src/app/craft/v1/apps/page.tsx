"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import useOnMount from "@/hooks/useOnMount";
import { cn } from "@opal/utils";
import type { IconFunctionComponent } from "@opal/types";
import { Button, Card, InputTypeIn, Text } from "@opal/components";
import { SettingsLayouts, toast } from "@opal/layouts";
import { SvgCheckCircle, SvgPlug, SvgSettings } from "@opal/icons";
import {
  ExternalAppUserResponse,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";
import {
  disconnectUserFromApp,
  startExternalAppOAuth,
  upsertUserCredentials,
} from "@/app/craft/services/externalAppsService";
import {
  disconnectMCPServer,
  saveMCPUserCredentials,
  startMCPUserOAuth,
} from "@/lib/tools/mcpService";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPServer,
  MCPServersResponse,
} from "@/lib/tools/interfaces";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { CRAFT_APPS_PATH } from "@/app/craft/v1/constants";
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

// Normalized view of anything connectable on this page — external apps and
// craft-enabled MCP servers render through the same card so users see one
// uniform "Apps" surface.
interface ConnectableApp {
  key: string;
  name: string;
  description: string;
  /** Deep-link (`?connect=`) target; external apps only. */
  slug: string | null;
  authenticated: boolean;
  logo: IconFunctionComponent;
  /** How the user connects; null = nothing for the user to do (org-managed). */
  connectMode: "oauth" | "credentials" | null;
  credentialKeys: string[];
  credentialValues: Record<string, string>;
  /** Returns the URL to redirect to for OAuth. */
  startOAuth: () => Promise<string>;
  saveCredentials: (values: Record<string, string>) => Promise<void>;
  /** Absent when there is no per-user credential to remove. */
  disconnect: (() => Promise<void>) | null;
}

function externalAppToConnectable(
  app: ExternalAppUserResponse
): ConnectableApp {
  return {
    key: `app-${app.id}`,
    name: app.name,
    description: app.description,
    slug: app.slug,
    authenticated: app.authenticated,
    logo: getAppTypeLogo(app.app_type),
    connectMode: app.app_type === "CUSTOM" ? "credentials" : "oauth",
    credentialKeys: app.credential_keys,
    credentialValues: app.credential_values,
    startOAuth: async () => (await startExternalAppOAuth(app.id)).authorize_url,
    saveCredentials: (values) => upsertUserCredentials(app.id, values),
    disconnect: () => disconnectUserFromApp(app.id),
  };
}

function mcpServerToConnectable(server: MCPServer): ConnectableApp | null {
  const perUser =
    server.auth_performer === MCPAuthenticationPerformer.PER_USER &&
    server.auth_type !== MCPAuthenticationType.NONE;
  const authenticated =
    server.user_authenticated ?? server.is_authenticated ?? false;
  // Org-managed (admin-performed / no-auth) servers with nothing configured
  // aren't actionable for the user — hide rather than show a dead card.
  if (!perUser && !authenticated) return null;
  const credentialKeys: string[] = server.auth_template?.required_fields?.length
    ? server.auth_template.required_fields
    : ["api_key"];
  return {
    key: `mcp-${server.id}`,
    name: server.name,
    description: server.description ?? "",
    slug: null,
    authenticated,
    logo: getActionIcon(server.server_url, server.name),
    connectMode: !perUser
      ? null
      : server.auth_type === MCPAuthenticationType.API_TOKEN
        ? "credentials"
        : "oauth",
    credentialKeys,
    credentialValues: server.user_credentials ?? {},
    startOAuth: async () =>
      (await startMCPUserOAuth(server.id, CRAFT_APPS_PATH)).oauth_url,
    saveCredentials: (values) => saveMCPUserCredentials(server.id, values),
    disconnect: perUser ? () => disconnectMCPServer(server.id) : null,
  };
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
  const connectSlug = useSearchParams().get("connect");

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
                highlight={connectSlug !== null && connectSlug === item.slug}
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
