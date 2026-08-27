"use client";

import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import useOnMount from "@/hooks/useOnMount";
import { cn } from "@opal/utils";
import {
  Button,
  Card,
  InputTypeIn,
  Tabs,
  Text,
  Tooltip,
} from "@opal/components";
import {
  ContentAction,
  IllustrationContent,
  Section,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { SvgNoResult, SvgUnPlugged } from "@opal/illustrations";
import { SvgAlertCircle, SvgPlug, SvgSettings } from "@opal/icons";
import { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";
import {
  ConnectableApp,
  ConnectableKind,
  externalAppToConnectable,
  KIND_ORDER,
  mcpServerToConnectable,
  parseConnectableTab,
  useConnectableTab,
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
    emptyTitle: string;
    empty: string;
  }
> = {
  app: {
    label: "Apps",
    blurb:
      "Integrations Onyx supports directly. Each comes with skills that teach Craft how to use it — start here.",
    emptyTitle: "No apps yet",
    empty: "No apps are configured for your organization yet.",
  },
  mcp: {
    label: "MCP servers",
    blurb:
      "Servers an admin made available to Craft. Use these when the app you need isn't listed under Apps, or when you specifically want a server's own MCP tools.",
    emptyTitle: "No MCP servers yet",
    empty: "No MCP servers have been made available to Craft.",
  },
};

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
  const [tab, setTab] = useConnectableTab();

  // Apps with at least one associated skill switched off. Both skill lists
  // matter: a built-in provider's associated skill is a built-in row, so
  // reading only `customs` misses every built-in app. Empty until the fetch
  // resolves, which is also what keeps an app from being warned about before
  // its skills are known.
  const appsNeedingSkillSetup = useMemo(() => {
    const needsSetup = new Set<number>();
    for (const skill of [
      ...(skillsData?.builtins ?? []),
      ...(skillsData?.customs ?? []),
    ]) {
      const externalAppId = skill.external_app?.external_app_id;
      if (externalAppId !== undefined && !skill.enabled) {
        needsSetup.add(externalAppId);
      }
    }
    return needsSetup;
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
    // Connected first, then by name: what you already have is what you most
    // often come here to check on or disconnect.
    const visible = (items: ConnectableApp[]) =>
      items
        .filter((item) => (q ? item.name.toLowerCase().includes(q) : true))
        .sort(
          (a, b) =>
            Number(b.authenticated) - Number(a.authenticated) ||
            compareByName(a, b)
        );
    return {
      byKind: { app: visible(allApps), mcp: visible(allMcp) },
      searching: q.length > 0,
      isLoading: externalApps === undefined && mcpData === undefined,
      isEmpty: allApps.length === 0 && allMcp.length === 0,
    };
  }, [externalApps, mcpData, query]);

  if (isLoading) {
    return (
      <Card background="none" border="dashed" rounding={4}>
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
      <KindSlot tab={tab}>
        {(kind) => (
          <Text font="secondary-body" color="text-03">
            {KIND_COPY[kind].blurb}
          </Text>
        )}
      </KindSlot>
      <KindSlot tab={tab} panel>
        {(kind, active) => (
          <ConnectableList
            kind={kind}
            items={byKind[kind]}
            searching={searching}
            // Only the visible kind may claim a deep link; the others are
            // rendered purely to hold their height.
            connectParam={active ? connectParam : null}
            appsNeedingSkillSetup={appsNeedingSkillSetup}
            onChange={refresh}
          />
        )}
      </KindSlot>
    </Tabs>
  );
}

interface KindSlotProps {
  tab: ConnectableKind;
  /** Wire the active kind up as the tab's panel (`role="tabpanel"`). */
  panel?: boolean;
  children: (kind: ConnectableKind, active: boolean) => ReactNode;
}

/**
 * Renders one piece of the page for every kind, stacked in a single grid cell
 * with only the active kind visible. Apps and MCP servers share the layout but
 * not their content lengths, so every slot reserves the tallest kind's height:
 * the page's geometry — and with it the scrollbar, which would otherwise
 * re-center the whole page sideways — stays put when the tab changes.
 */
function KindSlot({ tab, panel, children }: KindSlotProps) {
  return (
    <div className={cn("grid", !panel && "pt-6 pb-2")}>
      {KIND_ORDER.map((kind) => {
        const active = kind === tab;
        const content = children(kind, active);
        return (
          <div
            key={kind}
            className={cn("col-start-1 row-start-1", !active && "invisible")}
            aria-hidden={!active}
          >
            {!panel ? (
              content
            ) : active ? (
              <Tabs.Content value={kind}>{content}</Tabs.Content>
            ) : (
              // Mirrors the top padding Tabs.Content applies, so the height an
              // unselected kind holds matches what it occupies once selected.
              <div className="w-full pt-4">{content}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

interface ConnectableListProps {
  kind: ConnectableKind;
  items: ConnectableApp[];
  searching: boolean;
  connectParam: string | null;
  /** Ids of external apps with a disabled associated skill. */
  appsNeedingSkillSetup: Set<number>;
  onChange: () => void;
}

function ConnectableList({
  kind,
  items,
  searching,
  connectParam,
  appsNeedingSkillSetup,
  onChange,
}: ConnectableListProps) {
  const copy = KIND_COPY[kind];

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

  // One grid for both states — connected cards lead, then the rest. A card that
  // connects moves up into that group but keeps its shape, so the page's
  // geometry never changes. The tab's count carries the totals.
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
      {items.map((item) => (
        <ConnectableCard
          key={item.key}
          app={item}
          // Skills are an external-app concept, and only apps carry an id.
          needsSkillSetup={
            item.externalAppId !== null &&
            appsNeedingSkillSetup.has(item.externalAppId)
          }
          highlight={connectParam !== null && connectParam === item.connectId}
          onChange={onChange}
        />
      ))}
    </div>
  );
}

/**
 * The card's one-line status. Connecting swaps this and the action beside it;
 * clamped to a single line, it is also what holds every card to one height.
 */
function statusLine(app: ConnectableApp, needsSkillSetup: boolean): string {
  if (app.authenticated) {
    return needsSkillSetup
      ? "Connected · not all associated skills are enabled"
      : "Connected";
  }
  // Org-managed and not usable by this account (e.g. an admin config that
  // yields no credentials, or pass-through OAuth for a password-login user).
  // There is no user-side action.
  if (app.connectMode === null) {
    return "Not available for your account — ask an admin";
  }
  return app.description;
}

interface ConnectableCardProps {
  app: ConnectableApp;
  highlight?: boolean;
  /** Whether some of the app's associated skills are disabled. Always false
   * for MCP servers, which have no skills. */
  needsSkillSetup?: boolean;
  onChange: () => void;
}

/**
 * One card shape for every connectable, connected or not. Connecting swaps the
 * status line and the action row only — the card keeps its place in the grid.
 */
function ConnectableCard({
  app,
  highlight,
  needsSkillSetup = false,
  onChange,
}: ConnectableCardProps) {
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
          highlight && "ring-2 ring-action-selection-04"
        )}
      >
        <Card background="light" border="solid" rounding={4}>
          <ContentAction
            sizePreset="main-ui"
            variant="section"
            padding={0}
            center
            icon={Logo}
            title={app.name}
            titleMaxLines={1}
            description={statusLine(app, needsSkillSetup)}
            descriptionMaxLines={1}
            rightChildren={
              <Section flexDirection="row" width="fit" height="fit" gap={2}>
                {app.authenticated ? (
                  <>
                    {/* Only the problem state gets a glyph — "Connected" in the
                        status line already says the happy path. */}
                    {needsSkillSetup && (
                      <Tooltip tooltip="Not all associated skills are enabled. This app may not work correctly.">
                        <SvgAlertCircle
                          size={16}
                          className="text-status-warning-05"
                          aria-label="Skill setup required"
                        />
                      </Tooltip>
                    )}
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
                  </>
                ) : (
                  app.connectMode !== null && (
                    <Button disabled={isStarting} onClick={connect}>
                      {isStarting ? "Redirecting…" : "Connect"}
                    </Button>
                  )
                )}
              </Section>
            }
          />
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
