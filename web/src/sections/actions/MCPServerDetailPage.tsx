"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import useSWR, { useSWRConfig } from "swr";
import { Button, MessageCard, Modal, Tabs } from "@opal/components";
import { toast } from "@opal/layouts";
import { SvgServer } from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import { pluginDetailHref, withPluginSearchParams } from "@/lib/plugins/routes";
import {
  errorHandlingFetcher,
  isNotFoundError,
  isAuthStatusError,
} from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useDefaultAssistantConfiguration } from "@/lib/agents/hooks";
import { refreshMemberPluginCaches } from "@/lib/plugins/member";
import { can } from "@/lib/permissions/resource-actions";
import { MCPServerStatus, type MCPServer } from "@/lib/mcp/types";
import { refreshMCPServerTools, updateMCPServerStatus } from "@/lib/mcp/svc";
import { getActionIcon } from "@/lib/tools/utils";
import MCPServerDetailsPage from "@/sections/actions/modals/MCPServerDetailsPage";
import MCPAuthenticationPage from "@/sections/actions/modals/MCPAuthenticationPage";
import MCPServerToolsEditor from "@/sections/actions/MCPServerToolsEditor";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";
import { useUser } from "@/providers/UserProvider";
import {
  clearMcpChatEnableIntent,
  consumeMcpChatEnableIntent,
} from "@/sections/actions/mcpChatEnableIntent";

interface MCPServerDetailPageProps {
  serverId: number;
}

type DetailTab = "server" | "authentication" | "tools";

function parseDetailTab(value: string | null): DetailTab {
  return value === "authentication" || value === "tools" ? value : "server";
}

export default function MCPServerDetailPage({
  serverId,
}: MCPServerDetailPageProps) {
  const t = useTranslations("actions");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { mutate } = useSWRConfig();
  const defaultChat = useDefaultAssistantConfiguration();
  const { user, userResolution } = useUser();
  const actor = useRef(user?.id);
  useEffect(() => {
    actor.current = user?.id;
  }, [user?.id]);
  const enableChatIntent = searchParams.get("enable_chat_intent");
  const enableChatCompleted = useRef(false);
  const validId = Number.isSafeInteger(serverId) && serverId > 0;
  const {
    data: server,
    error,
    isLoading,
    mutate: mutateServer,
  } = useSWR<MCPServer, Error>(
    validId ? SWR_KEYS.adminMcpServer(serverId) : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      shouldRetryOnError: (cause) =>
        !isNotFoundError(cause) && !isAuthStatusError(cause),
    }
  );
  const [tab, setTab] = useState<DetailTab>(() =>
    searchParams.get("trigger_fetch") === "true"
      ? "tools"
      : parseDetailTab(searchParams.get("tab"))
  );
  const [visited, setVisited] = useState<Set<DetailTab>>(() => new Set([tab]));
  const [detailsDirty, setDetailsDirty] = useState(false);
  const [authDirty, setAuthDirty] = useState(false);
  const [toolsDirty, setToolsDirty] = useState(false);
  const [detailsBusy, setDetailsBusy] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [toolsBusy, setToolsBusy] = useState(false);
  const [discoveringTools, setDiscoveringTools] = useState(false);
  const [revision, setRevision] = useState(0);
  const [footerTarget, setFooterTarget] = useState<HTMLDivElement | null>(null);
  const handledOAuthReturn = useRef(false);
  const busy = detailsBusy || authBusy || toolsBusy || discoveringTools;
  const guard = useUnsavedChangesGuard({
    isDirty: detailsDirty || authDirty || toolsDirty,
    onDiscard: () => {
      setDetailsDirty(false);
      setAuthDirty(false);
      setToolsDirty(false);
      setRevision((value) => value + 1);
    },
  });
  const close = () => {
    if (busy) return;
    guard.requestLeave(() => {
      clearMcpChatEnableIntent(enableChatIntent);
      router.replace(ADMIN_ROUTES.PLUGINS.path);
    });
  };
  const selectTab = useCallback(
    (nextTab: DetailTab) => {
      setVisited((current) => new Set([...current, nextTab]));
      setTab(nextTab);
      const query = new URLSearchParams(searchParams.toString());
      query.set("tab", nextTab);
      query.delete("trigger_fetch");
      if (
        enableChatCompleted.current ||
        searchParams.get("trigger_fetch") === "true"
      ) {
        query.delete("enable_chat");
        query.delete("enable_chat_intent");
      }
      router.replace(
        withPluginSearchParams(
          pluginDetailHref({ kind: "mcp", id: serverId }),
          query
        ),
        { scroll: false }
      );
    },
    [router, serverId, searchParams]
  );
  const refresh = useCallback(async () => {
    await Promise.all([mutateServer(), mutate(SWR_KEYS.adminMcpServers)]);
  }, [mutateServer, mutate]);
  const fetchTools = useCallback(
    async (id: number, token = enableChatIntent) => {
      setDiscoveringTools(true);
      try {
        await updateMCPServerStatus(id, MCPServerStatus.FETCHING_TOOLS);
        await mutateServer(
          (current) =>
            current
              ? { ...current, status: MCPServerStatus.FETCHING_TOOLS }
              : current,
          { revalidate: false }
        );
        const tools = await refreshMCPServerTools(id);
        await mutate(SWR_KEYS.adminMcpServerToolSnapshots(id), tools, {
          revalidate: false,
        });
        if (
          token &&
          !enableChatCompleted.current &&
          defaultChat.canEdit &&
          server &&
          can(server, "edit") &&
          tools.length > 0
        ) {
          if (!defaultChat.data || defaultChat.error)
            throw new Error(t("addMcpModal.toasts.updateFailed"));
          if (
            consumeMcpChatEnableIntent(token, {
              userId: actor.current,
              serverId: id,
            })
          ) {
            await defaultChat.updateTools(
              tools.map((tool) => tool.id),
              true
            );
            enableChatCompleted.current = true;
            selectTab("tools");
          }
        }
        await refreshMemberPluginCaches(mutate);
      } finally {
        await refresh().catch((cause: unknown) =>
          console.error(
            "Failed to refresh MCP server after loading tools",
            cause
          )
        );
        setDiscoveringTools(false);
      }
    },
    [
      mutate,
      mutateServer,
      refresh,
      enableChatIntent,
      defaultChat,
      server,
      selectTab,
      t,
    ]
  );
  useEffect(() => {
    if (
      !server ||
      searchParams.get("trigger_fetch") !== "true" ||
      (enableChatIntent && defaultChat.isLoading) ||
      (enableChatIntent && userResolution !== "resolved") ||
      handledOAuthReturn.current
    )
      return;
    handledOAuthReturn.current = true;
    selectTab("tools");
    void fetchTools(server.id).catch((cause: unknown) => {
      clearMcpChatEnableIntent(enableChatIntent);
      toast.error(
        t("mcpPage.toasts.fetchToolsFailed", {
          error:
            cause instanceof Error
              ? cause.message
              : t("mcpPage.errors.unknown"),
        })
      );
    });
  }, [
    server,
    searchParams,
    selectTab,
    fetchTools,
    enableChatIntent,
    t,
    enableChatIntent,
    defaultChat.isLoading,
    userResolution,
  ]);
  const saveDetails = async (saved: MCPServer) => {
    await mutateServer(
      (current) =>
        current
          ? {
              ...current,
              name: saved.name,
              description: saved.description,
              is_public: saved.is_public,
              groups: saved.groups,
              users: saved.users,
            }
          : saved,
      { revalidate: false }
    );
    try {
      const fresh = await errorHandlingFetcher<MCPServer>(
        SWR_KEYS.adminMcpServer(saved.id)
      );
      await mutateServer(fresh, { revalidate: false });
    } catch (cause) {
      console.error("Failed to reload MCP server after saving", cause);
    }
    await mutate(SWR_KEYS.adminMcpServers).catch((cause: unknown) => {
      console.error("Failed to refresh MCP overview after saving", cause);
    });
  };
  const canEdit = !!server && can(server, "edit");

  const body = (
    <>
      {isLoading ? (
        <IconLoader />
      ) : !server || error ? (
        <div className="flex flex-col items-start gap-4">
          <MessageCard
            variant="error"
            title={t(
              !validId || isNotFoundError(error)
                ? "mcpDetail.notFound"
                : "mcpDetail.loadError"
            )}
            description={t("mcpDetail.unavailable")}
          />
          {validId && !isNotFoundError(error) && !isAuthStatusError(error) && (
            <Button prominence="secondary" onClick={() => void mutateServer()}>
              {t("mcpDetail.retry")}
            </Button>
          )}
        </div>
      ) : (
        <Tabs
          value={tab}
          onValueChange={(value) => {
            if (!busy) selectTab(parseDetailTab(value));
          }}
          variant="contained"
          gap={6}
        >
          <Tabs.List>
            <Tabs.Trigger value="server" disabled={busy}>
              {t("mcpDetail.configuration")}
            </Tabs.Trigger>
            <Tabs.Trigger value="authentication" disabled={busy}>
              {t("mcpDetail.authentication")}
            </Tabs.Trigger>
            <Tabs.Trigger value="tools" disabled={busy}>
              {t("mcpTools.title")}
            </Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value="server" keepMounted hidden={tab !== "server"}>
            {visited.has("server") && (
              <fieldset
                disabled={busy && !detailsBusy}
                className="w-full min-w-0"
              >
                <MCPServerDetailsPage
                  key={`${server.id}:${revision}`}
                  variant="page"
                  readOnly={!canEdit}
                  active={tab === "server"}
                  footerTarget={footerTarget}
                  server={server}
                  onSaved={saveDetails}
                  onBusyChange={setDetailsBusy}
                  onDirtyChange={setDetailsDirty}
                />
              </fieldset>
            )}
          </Tabs.Content>
          <Tabs.Content
            value="authentication"
            keepMounted
            hidden={tab !== "authentication"}
          >
            {visited.has("authentication") && (
              <fieldset
                disabled={discoveringTools || detailsBusy || toolsBusy}
                className="w-full min-w-0"
              >
                <MCPAuthenticationPage
                  key={`${server.id}:${server.server_url}:${revision}`}
                  variant="page"
                  readOnly={!canEdit}
                  active={tab === "authentication"}
                  footerTarget={footerTarget}
                  mcpServer={server}
                  chatEnableIntent={
                    defaultChat.canEdit ? enableChatIntent : null
                  }
                  canSubmit={
                    !enableChatIntent ||
                    !defaultChat.canEdit ||
                    !!defaultChat.data
                  }
                  onTriggerFetchTools={fetchTools}
                  onBusyChange={setAuthBusy}
                  onDirtyChange={setAuthDirty}
                  onSaved={refresh}
                  onComplete={() => selectTab("tools")}
                />
              </fieldset>
            )}
          </Tabs.Content>
          <Tabs.Content value="tools" keepMounted hidden={tab !== "tools"}>
            {visited.has("tools") && (
              <fieldset
                disabled={discoveringTools || detailsBusy || authBusy}
                aria-busy={discoveringTools}
                className="w-full min-w-0"
              >
                <MCPServerToolsEditor
                  key={`${server.id}:${revision}`}
                  server={server}
                  onDirtyChange={setToolsDirty}
                  onBusyChange={setToolsBusy}
                  onSaved={refresh}
                  active={tab === "tools"}
                  footerTarget={footerTarget}
                />
              </fieldset>
            )}
          </Tabs.Content>
        </Tabs>
      )}
    </>
  );
  const dialogs = (
    <UnsavedChangesModal
      open={guard.confirmationOpen}
      onCancel={guard.cancelLeave}
      onDiscard={guard.discardAndLeave}
    />
  );
  const title = server?.name ?? t("mcpDetail.configuration");
  const icon = server
    ? getActionIcon(server.server_url, server.name) || SvgServer
    : SvgServer;

  return (
    <>
      <Modal
        open
        onOpenChange={(open) => {
          if (!open) close();
        }}
      >
        <PluginModalContent>
          <Modal.Header
            icon={icon}
            title={title}
            description={server?.server_url}
            onClose={close}
          />
          <Modal.Body twoTone={false} alignItems="stretch">
            {body}
          </Modal.Body>
          <Modal.Footer justifyContent="between" padding={4}>
            <div
              ref={setFooterTarget}
              className="ms-auto flex items-center gap-2"
            />
          </Modal.Footer>
        </PluginModalContent>
      </Modal>
      {dialogs}
    </>
  );
}
