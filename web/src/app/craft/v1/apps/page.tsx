"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import useOnMount from "@/hooks/useOnMount";
import { cn } from "@opal/utils";
import { Button, Card, InputTypeIn, Tabs, Text } from "@opal/components";
import {
  Content,
  ContentAction,
  IllustrationContent,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { SvgNoResult, SvgUnPlugged } from "@opal/illustrations";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgPlug,
  SvgSettings,
} from "@opal/icons";
import { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";
import { MCPServersResponse } from "@/lib/tools/interfaces";
import {
  ConnectableApp,
  ConnectableKind,
  CRAFT_APPS_TAB_PARAM,
  externalAppToConnectable,
  mcpServerToConnectable,
  parseConnectableTab,
} from "@/app/craft/v1/apps/connectableApps";
import UserCredentialsModal from "@/app/craft/v1/apps/UserCredentialsModal";
import { useUser } from "@/providers/UserProvider";
import useUserSkills from "@/hooks/useUserSkills";
import { useCraftMcpServers } from "@/lib/tools/hooks";
import { compareByName } from "@/lib/skills/picker";

// Apps and MCP servers are connected, governed, and taught to the agent
// differently, so each kind gets its own tab rather than one blended list.
const KIND_COPY: Record<
  ConnectableKind,
  {
    label: string;
    blurb: string;
    browseLabel: string;
    emptyTitle: string;
    empty: string;
  }
> = {
  app: {
    label: "Apps",
    blurb:
      "Integrations Onyx supports directly. Each comes with skills that teach Craft how to use it — start here.",
    browseLabel: "Browse apps",
    emptyTitle: "No apps yet",
    empty: "No apps are configured for your organization yet.",
  },
  mcp: {
    label: "MCP servers",
    blurb:
      "Servers an admin made available to Craft. Use these when the app you need isn't listed under Apps, or when you specifically want a server's own MCP tools.",
    browseLabel: "Browse servers",
    emptyTitle: "No MCP servers yet",
    empty: "No MCP servers have been made available to Craft.",
  },
};

const KIND_ORDER: ConnectableKind[] = ["app", "mcp"];

interface SkillSetup {
  total: number;
  selected: number;
}

/** Readiness of an app's associated skills. `"unknown"` covers both "skills
 * haven't loaded" and "not an external app", neither of which should claim
 * readiness. */
type SkillStatus = "unknown" | "ready" | "needs-setup";

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
  const { data: mcpData, refresh: refreshMcp } = useCraftMcpServers();
  const { data: skillsData, refresh: refreshSkills } = useUserSkills();
  const searchParams = useSearchParams();
  const connectParam = searchParams.get("connect");
  const urlTab = parseConnectableTab(searchParams.get(CRAFT_APPS_TAB_PARAM));
  // The tab is deep-linkable (`?tab=mcp`), so the URL drives it — including on a
  // client-side navigation from this same page, which doesn't remount.
  const [tab, setTab] = useState<ConnectableKind>(urlTab);
  useEffect(() => setTab(urlTab), [urlTab]);

  const skillSetupByAppId = useMemo(() => {
    const setup = new Map<number, SkillSetup>();
    // Both lists matter: a built-in provider's associated skill is a built-in
    // skill row, so reading only `customs` misses every built-in app.
    const skills = [
      ...(skillsData?.builtins ?? []),
      ...(skillsData?.customs ?? []),
    ];
    for (const skill of skills) {
      const externalAppId = skill.external_app?.external_app_id;
      if (externalAppId === undefined) continue;
      const current = setup.get(externalAppId) ?? { total: 0, selected: 0 };
      current.total += 1;
      if (skill.enabled) current.selected += 1;
      setup.set(externalAppId, current);
    }
    return setup;
  }, [skillsData]);

  const refresh = () => {
    void mutateApps();
    void refreshMcp();
    void refreshSkills();
  };

  const { byKind, searching, isLoading, isEmpty } = useMemo(() => {
    const allApps = (externalApps ?? []).map(externalAppToConnectable);
    const allMcp = (mcpData?.mcp_servers ?? []).map(mcpServerToConnectable);
    const q = query.trim().toLowerCase();
    const visible = (items: ConnectableApp[]) =>
      items
        .filter((item) => (q ? item.name.toLowerCase().includes(q) : true))
        .sort(compareByName);
    return {
      byKind: { app: visible(allApps), mcp: visible(allMcp) },
      searching: q.length > 0,
      isLoading: externalApps === undefined && mcpData === undefined,
      isEmpty: allApps.length === 0 && allMcp.length === 0,
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
      <IllustrationContent
        illustration={SvgUnPlugged}
        title="Nothing to connect yet"
        description="No apps or MCP servers are configured for your organization yet."
      />
    );
  }

  // `?connect=` deep-links only ever target an external app; `?tab=mcp` is how
  // the input-bar picker lands a user on an MCP server they need to connect.
  return (
    <Tabs
      value={tab}
      onValueChange={(next) => setTab(parseConnectableTab(next))}
    >
      <Tabs.List>
        {KIND_ORDER.map((kind) => (
          <Tabs.Trigger
            key={kind}
            value={kind}
          >{`${KIND_COPY[kind].label} · ${byKind[kind].length}`}</Tabs.Trigger>
        ))}
      </Tabs.List>
      {KIND_ORDER.map((kind) => (
        <Tabs.Content key={kind} value={kind}>
          <ConnectableList
            kind={kind}
            items={byKind[kind]}
            searching={searching}
            connectParam={connectParam}
            skillsLoaded={skillsData !== undefined}
            skillSetupByAppId={skillSetupByAppId}
            onChange={refresh}
          />
        </Tabs.Content>
      ))}
    </Tabs>
  );
}

interface ConnectableListProps {
  kind: ConnectableKind;
  items: ConnectableApp[];
  searching: boolean;
  connectParam: string | null;
  /** False until the skills fetch resolves; readiness is unknown until then. */
  skillsLoaded: boolean;
  skillSetupByAppId: Map<number, SkillSetup>;
  onChange: () => void;
}

function ConnectableList({
  kind,
  items,
  searching,
  connectParam,
  skillsLoaded,
  skillSetupByAppId,
  onChange,
}: ConnectableListProps) {
  const copy = KIND_COPY[kind];
  const connected = items.filter((item) => item.authenticated);
  const browse = items.filter((item) => !item.authenticated);

  // Skill enablement is an external-app concept — MCP servers expose MCP tools,
  // not skills, so their rows carry no readiness state at all.
  function skillStatusOf(item: ConnectableApp): SkillStatus {
    if (item.kind !== "app" || !skillsLoaded) return "unknown";
    const setup =
      item.externalAppId === null
        ? undefined
        : skillSetupByAppId.get(item.externalAppId);
    if (
      setup !== undefined &&
      setup.total > 0 &&
      setup.selected < setup.total
    ) {
      return "needs-setup";
    }
    return "ready";
  }

  if (items.length === 0) {
    return searching ? (
      <IllustrationContent
        illustration={SvgNoResult}
        title="No matches"
        description="Nothing here matches your search."
      />
    ) : (
      <IllustrationContent
        illustration={SvgUnPlugged}
        title={copy.emptyTitle}
        description={copy.empty}
      />
    );
  }

  return (
    <div className="flex flex-col gap-6 pt-2">
      <Text font="secondary-body" color="text-03">
        {copy.blurb}
      </Text>

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
                skillStatus={skillStatusOf(item)}
                onChange={onChange}
              />
            ))}
          </div>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <Text font="secondary-body" color="text-03">
          {copy.browseLabel}
        </Text>
        {browse.length === 0 ? (
          <Text font="secondary-body" color="text-03">
            Everything is connected.
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
                onChange={onChange}
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
  /** Row variant only: whether the app's skills are ready to use. */
  skillStatus?: SkillStatus;
  onChange: () => void;
}

function ProviderConnectCard({
  app,
  variant,
  highlight,
  skillStatus = "unknown",
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
  const needsSkillSetup = skillStatus === "needs-setup";

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
            <ContentAction
              sizePreset="main-ui"
              variant="section"
              padding="fit"
              center
              icon={Logo}
              title={app.name}
              description={
                needsSkillSetup
                  ? "Connected · Not all associated skills are enabled. This app may not work correctly."
                  : "Connected"
              }
              rightChildren={
                <div className="flex items-center gap-2">
                  {needsSkillSetup ? (
                    <SvgAlertCircle
                      className="w-4 h-4 text-status-warning-05"
                      aria-label="Skill setup required"
                    />
                  ) : skillStatus === "ready" ? (
                    <SvgCheckCircle
                      className="w-4 h-4 text-status-success-05"
                      aria-label="App ready"
                    />
                  ) : null}
                  {needsSkillSetup && app.externalAppId !== null && (
                    <Button
                      prominence="secondary"
                      href={`/craft/v1/skills?externalAppId=${app.externalAppId}`}
                    >
                      Review skills
                    </Button>
                  )}
                  {app.disconnect && (
                    <Button
                      prominence={needsSkillSetup ? "tertiary" : "secondary"}
                      disabled={isStarting}
                      onClick={disconnect}
                    >
                      {isStarting ? "…" : "Disconnect"}
                    </Button>
                  )}
                </div>
              }
            />
          ) : (
            <div className="flex flex-col gap-3 w-full">
              <Content
                sizePreset="main-ui"
                variant="section"
                icon={Logo}
                title={app.name}
                description={app.description}
              />
              {app.connectMode === null ? (
                // Org-managed and not usable by this account (e.g. an admin
                // config that yields no credentials, or pass-through OAuth for a
                // password-login user). There is no user-side action.
                <Text font="secondary-body" color="text-03">
                  Not available for your account — ask an admin to check this
                  connection.
                </Text>
              ) : (
                <Button disabled={isStarting} onClick={connect}>
                  {isStarting ? "Redirecting…" : "Connect"}
                </Button>
              )}
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
