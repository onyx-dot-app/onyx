"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import useSWR, { useSWRConfig } from "swr";
import {
  Button,
  InputSwitch,
  MessageCard,
  Modal,
  Tabs,
  Text,
} from "@opal/components";
import {
  Content,
  InputHorizontal,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { SvgArrowLeft, SvgServer, SvgTrash } from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  errorHandlingFetcher,
  isNotFoundError,
  isAuthStatusError,
} from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { can } from "@/lib/permissions/resource-actions";
import { useSettings } from "@/lib/settings/hooks";
import { MCPServerStatus, type MCPServer } from "@/lib/mcp/types";
import {
  deleteMCPServer,
  refreshMCPServerTools,
  updateMCPServer,
  updateMCPServerStatus,
} from "@/lib/mcp/svc";
import { getActionIcon } from "@/lib/tools/utils";
import MCPServerDetailsPage from "@/sections/actions/modals/MCPServerDetailsPage";
import MCPAuthenticationPage from "@/sections/actions/modals/MCPAuthenticationPage";
import MCPServerToolsEditor from "@/sections/actions/MCPServerToolsEditor";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";
import { useDefaultAssistantConfiguration } from "@/lib/agents/hooks";
import type { ToolSnapshot } from "@/lib/tools/types";

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
  const settings = useSettings();
  const defaultChat = useDefaultAssistantConfiguration();
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
  const { data: serverTools, error: toolsError } = useSWR<
    ToolSnapshot[],
    Error
  >(
    validId ? SWR_KEYS.adminMcpServerToolSnapshots(serverId) : null,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
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
  const [availabilitySaving, setAvailabilitySaving] = useState(false);
  const [revision, setRevision] = useState(0);
  const [authRevision, setAuthRevision] = useState(0);
  const [deleteRequested, setDeleteRequested] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmUrlChange, setConfirmUrlChange] = useState(false);
  const urlChangeDecision = useRef<((confirmed: boolean) => void) | null>(null);
  const handledOAuthReturn = useRef(false);
  const busy =
    detailsBusy ||
    authBusy ||
    toolsBusy ||
    discoveringTools ||
    availabilitySaving ||
    defaultChat.isSaving ||
    deleting;
  const guard = useUnsavedChangesGuard({
    isDirty: detailsDirty || authDirty || toolsDirty,
    onDiscard: () => {
      setDetailsDirty(false);
      setAuthDirty(false);
      setToolsDirty(false);
      setRevision((value) => value + 1);
    },
  });
  const selectTab = useCallback(
    (nextTab: DetailTab) => {
      setVisited((current) => new Set([...current, nextTab]));
      setTab(nextTab);
      router.replace(`/admin/mcp-actions/${serverId}?tab=${nextTab}`, {
        scroll: false,
      });
    },
    [router, serverId]
  );
  const refresh = useCallback(async () => {
    await Promise.all([mutateServer(), mutate(SWR_KEYS.adminMcpServers)]);
  }, [mutateServer, mutate]);
  const fetchTools = useCallback(
    async (id: number) => {
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
    [mutate, mutateServer, refresh]
  );
  useEffect(() => {
    if (
      !server ||
      searchParams.get("trigger_fetch") !== "true" ||
      handledOAuthReturn.current
    )
      return;
    handledOAuthReturn.current = true;
    selectTab("tools");
    void fetchTools(server.id).catch((cause: unknown) => {
      toast.error(
        t("mcpPage.toasts.fetchToolsFailed", {
          error:
            cause instanceof Error
              ? cause.message
              : t("mcpPage.errors.unknown"),
        })
      );
    });
  }, [server, searchParams, selectTab, fetchTools, t]);
  const beforeUrlChange = () => {
    if (!authDirty) return Promise.resolve(true);
    setConfirmUrlChange(true);
    return new Promise<boolean>((resolve) => {
      urlChangeDecision.current = resolve;
    });
  };
  const resolveUrlChange = (confirmed: boolean) => {
    setConfirmUrlChange(false);
    urlChangeDecision.current?.(confirmed);
    urlChangeDecision.current = null;
  };
  const saveDetails = async (saved: MCPServer) => {
    if (server?.server_url !== saved.server_url) {
      // The old endpoint's secrets are invalid even if the detail reload fails.
      setAuthDirty(false);
      setAuthRevision((value) => value + 1);
      await mutateServer(
        {
          ...saved,
          admin_credentials: undefined,
          user_credentials: undefined,
          auth_template: null,
        },
        { revalidate: false }
      );
    } else {
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
    }
    // PATCH returns a summary; reload the detail before adopting its credentials.
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
  const changeDefaultChat = async (checked: boolean) => {
    if (!serverTools || busy) return;
    try {
      await defaultChat.updateTools(
        serverTools.map((tool) => tool.id),
        checked
      );
      toast.success(t("mcpDetail.availabilitySaved"));
    } catch (cause) {
      toast.error(
        cause instanceof Error
          ? cause.message
          : t("addMcpModal.toasts.updateFailed")
      );
    }
  };
  const changeCraft = async (checked: boolean) => {
    if (!server || busy || !can(server, "edit")) return;
    setAvailabilitySaving(true);
    try {
      await updateMCPServer(server.id, { available_in_craft: checked });
      await mutateServer(
        (current) =>
          current ? { ...current, available_in_craft: checked } : current,
        { revalidate: false }
      );
      toast.success(t("mcpDetail.availabilitySaved"));
      void mutate(SWR_KEYS.adminMcpServers).catch(console.error);
    } catch (cause) {
      toast.error(
        cause instanceof Error
          ? cause.message
          : t("addMcpModal.toasts.updateFailed")
      );
    } finally {
      setAvailabilitySaving(false);
    }
  };
  const deleteServer = async () => {
    if (deleting) return;
    setDeleting(true);
    try {
      await deleteMCPServer(serverId);
      await mutate(SWR_KEYS.adminMcpServers).catch(console.error);
      router.push(ADMIN_ROUTES.MCP_ACTIONS.path);
    } catch (cause) {
      toast.error(
        cause instanceof Error
          ? cause.message
          : t("mcpPage.toasts.deleteFailed")
      );
      setDeleting(false);
    }
  };
  const canEdit = !!server && can(server, "edit");
  const availability = (
    <section className="flex flex-col gap-5 border-t border-border-01 pt-6">
      <Content
        title={t("mcpDetail.availability")}
        sizePreset="main-content"
        variant="section"
      />
      {defaultChat.canEdit &&
        (defaultChat.error || toolsError ? (
          <MessageCard
            variant="error"
            title={t("mcpDetail.loadError")}
            description={(defaultChat.error ?? toolsError)?.message}
          />
        ) : !defaultChat.data || !serverTools ? (
          <IconLoader />
        ) : (
          <InputHorizontal
            withLabel="mcp-default-chat"
            title={t("addMcpModal.defaultChat.title")}
            description={t("addMcpModal.defaultChat.description")}
            center
          >
            <InputSwitch
              id="mcp-default-chat"
              aria-label={t("addMcpModal.defaultChat.title")}
              checked={
                serverTools?.some((tool) =>
                  defaultChat.data?.tool_ids.includes(tool.id)
                ) ?? false
              }
              disabled={
                !defaultChat.canEdit ||
                !defaultChat.data ||
                !!defaultChat.error ||
                !serverTools?.length ||
                !!toolsError ||
                busy ||
                toolsDirty
              }
              onCheckedChange={(checked) => void changeDefaultChat(checked)}
            />
          </InputHorizontal>
        ))}
      {settings.onyx_craft_available === true && (
        <InputHorizontal
          withLabel="mcp-craft"
          title={t("addMcpModal.craft.title")}
          description={t("addMcpModal.craft.description")}
          center
        >
          <InputSwitch
            id="mcp-craft"
            aria-label={t("addMcpModal.craft.title")}
            checked={server?.available_in_craft ?? false}
            disabled={!canEdit || busy}
            onCheckedChange={(checked) => void changeCraft(checked)}
          />
        </InputHorizontal>
      )}
    </section>
  );

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={
          server
            ? getActionIcon(server.server_url, server.name) || SvgServer
            : SvgServer
        }
        title={server?.name ?? t("mcpDetail.configuration")}
        description={server?.description || undefined}
        divider
      >
        <Button
          icon={SvgArrowLeft}
          prominence="tertiary"
          size="sm"
          href={ADMIN_ROUTES.MCP_ACTIONS.path}
        >
          {t("mcpDetail.back")}
        </Button>
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>
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
            {validId &&
              !isNotFoundError(error) &&
              !isAuthStatusError(error) && (
                <Button
                  prominence="secondary"
                  onClick={() => void mutateServer()}
                >
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
                    editOnly
                    readOnly={!canEdit}
                    active={tab === "server"}
                    footerTarget={null}
                    server={server}
                    onSaved={saveDetails}
                    onBusyChange={setDetailsBusy}
                    onDirtyChange={setDetailsDirty}
                    onBeforeUrlChange={beforeUrlChange}
                    afterFields={availability}
                    onDelete={
                      can(server, "delete")
                        ? () => setDeleteRequested(true)
                        : undefined
                    }
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
                  disabled={
                    discoveringTools ||
                    detailsBusy ||
                    toolsBusy ||
                    availabilitySaving
                  }
                  className="w-full min-w-0"
                >
                  <MCPAuthenticationPage
                    key={`${server.id}:${server.server_url}:${revision}:${authRevision}`}
                    variant="page"
                    readOnly={!canEdit}
                    active={tab === "authentication"}
                    footerTarget={null}
                    mcpServer={server}
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
                  disabled={
                    discoveringTools ||
                    detailsBusy ||
                    authBusy ||
                    availabilitySaving
                  }
                  aria-busy={discoveringTools}
                  className="w-full min-w-0"
                >
                  <MCPServerToolsEditor
                    key={`${server.id}:${revision}`}
                    server={server}
                    onDirtyChange={setToolsDirty}
                    onBusyChange={setToolsBusy}
                    onSaved={refresh}
                  />
                </fieldset>
              )}
            </Tabs.Content>
          </Tabs>
        )}
      </SettingsLayouts.Body>
      <UnsavedChangesModal
        open={guard.confirmationOpen}
        onCancel={guard.cancelLeave}
        onDiscard={guard.discardAndLeave}
      />
      <UnsavedChangesModal
        open={confirmUrlChange}
        onCancel={() => resolveUrlChange(false)}
        onDiscard={() => resolveUrlChange(true)}
      />
      {deleteRequested && server && (
        <Modal
          open
          onOpenChange={(open) => {
            if (!open && !deleting) setDeleteRequested(false);
          }}
        >
          <Modal.Content width="sm" preventAccidentalClose={false}>
            <Modal.Header
              icon={SvgTrash}
              title={t("mcpCard.deleteModal.title")}
              onClose={() => {
                if (!deleting) setDeleteRequested(false);
              }}
            />
            <Modal.Body>
              <Text as="p" color="text-03">
                {t.markup("mcpCard.deleteModal.body.description", {
                  title: server.name,
                  emphasis: (chunks) => chunks,
                })}
              </Text>
              <Text as="p" color="text-03">
                {t("mcpCard.deleteModal.body.confirmation")}
              </Text>
            </Modal.Body>
            <Modal.Footer>
              <Button
                prominence="secondary"
                disabled={deleting}
                onClick={() => setDeleteRequested(false)}
              >
                {t("addMcpModal.cancelButton.label")}
              </Button>
              <Button
                variant="danger"
                disabled={deleting}
                onClick={deleteServer}
              >
                {t("mcpCard.deleteModal.submitButton.label")}
              </Button>
            </Modal.Footer>
          </Modal.Content>
        </Modal>
      )}
    </SettingsLayouts.Root>
  );
}
