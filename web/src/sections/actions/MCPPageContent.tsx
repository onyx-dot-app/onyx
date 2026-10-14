"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useSWRConfig } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useTranslations } from "next-intl";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import MCPActionCard from "@/sections/actions/MCPActionCard";
import AdminListHeader from "@/sections/admin/AdminListHeader";
import ActionCardSkeleton from "@/sections/actions/skeleton/ActionCardSkeleton";
import { getActionIcon } from "@/lib/tools/utils";
import { ActionStatus } from "@/lib/tools/types";
import { MCPServerStatus, MCPServer } from "@/lib/mcp/types";
import { toast } from "@opal/layouts";
import { useCreateModal } from "@opal/components";
import MCPServerSetupModal from "@/sections/actions/modals/MCPServerSetupModal";
import { refreshMCPServerTools, updateMCPServerStatus } from "@/lib/mcp/svc";
import { useSearchParams } from "next/navigation";
import { useRouter } from "next/navigation";
import { useAdminMcpServers } from "@/lib/mcp/hooks";

export default function MCPPageContent() {
  const t = useTranslations("actions");
  const { mutate } = useSWRConfig();

  // Data fetching
  const {
    mcpData,
    isLoading: isMcpLoading,
    mutateMcpServers,
  } = useAdminMcpServers();

  // Modal management
  const manageServerModal = useCreateModal();

  // Local state
  const [searchQuery, setSearchQuery] = useState("");

  const mcpServers = useMemo<MCPServer[]>(
    () => mcpData?.mcp_servers || [],
    [mcpData?.mcp_servers]
  );
  const isLoading = isMcpLoading;

  const searchParams = useSearchParams();
  const router = useRouter();

  const handledOAuthReturn = useRef<string | null>(null);
  useEffect(() => {
    const serverId = searchParams.get("server_id");
    if (
      serverId &&
      /^\d+$/.test(serverId) &&
      Number(serverId) > 0 &&
      searchParams.get("trigger_fetch") === "true" &&
      handledOAuthReturn.current !== serverId
    ) {
      handledOAuthReturn.current = serverId;
      router.replace(
        `${ADMIN_ROUTES.MCP_ACTIONS.path}/${serverId}?trigger_fetch=true`
      );
    }
  }, [searchParams, router]);

  // Determine action status based on server status field
  const getActionStatusForServer = useCallback(
    (server: MCPServer): ActionStatus => {
      if (server.status === MCPServerStatus.CONNECTED) {
        return ActionStatus.CONNECTED;
      } else if (
        server.status === MCPServerStatus.AWAITING_AUTH ||
        server.status === MCPServerStatus.CREATED
      ) {
        return ActionStatus.PENDING;
      } else if (server.status === MCPServerStatus.FETCHING_TOOLS) {
        return ActionStatus.FETCHING;
      }
      return ActionStatus.DISCONNECTED;
    },
    []
  );

  const triggerFetchToolsInPlace = useCallback(
    async (serverId: number) => {
      try {
        await updateMCPServerStatus(serverId, MCPServerStatus.FETCHING_TOOLS);
        await mutateMcpServers();

        const tools = await refreshMCPServerTools(serverId);
        await mutate(SWR_KEYS.adminMcpServerToolSnapshots(serverId), tools, {
          revalidate: false,
        });

        toast.success(t("mcpPage.toasts.toolsFetched"));

        await mutateMcpServers();
      } catch (error) {
        // The setup form owns the error and must remain open for correction.
        await mutateMcpServers().catch(() => undefined);
        throw error;
      }
    },
    [mutateMcpServers, mutate, t]
  );

  const handleAddServer = useCallback(() => {
    manageServerModal.toggle(true);
  }, [manageServerModal]);

  // Filter servers based on search query
  const filteredServers = useMemo(() => {
    if (!searchQuery.trim()) return mcpServers;

    const query = searchQuery.toLowerCase();
    return mcpServers.filter(
      (server) =>
        server.name.toLowerCase().includes(query) ||
        server.description?.toLowerCase().includes(query) ||
        server.server_url.toLowerCase().includes(query)
    );
  }, [mcpServers, searchQuery]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="shrink-0 mb-4">
        <AdminListHeader
          hasItems={isLoading || mcpServers.length > 0}
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          onAction={handleAddServer}
          actionLabel={t("mcpPage.addButton.label")}
          emptyStateText={t("mcpPage.empty.description")}
        />
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="grid grid-cols-1 md:grid-cols-2 items-start gap-4 w-full pb-4">
          {isLoading ? (
            <>
              <ActionCardSkeleton />
              <ActionCardSkeleton />
            </>
          ) : (
            filteredServers.map((server) => {
              const status = getActionStatusForServer(server);

              return (
                <MCPActionCard
                  key={server.id}
                  title={server.name}
                  description={server.description || server.server_url}
                  logo={getActionIcon(server.server_url, server.name)}
                  status={status}
                  toolCount={server.tool_count}
                  onOpen={() =>
                    router.push(`${ADMIN_ROUTES.MCP_ACTIONS.path}/${server.id}`)
                  }
                />
              );
            })
          )}
        </div>
      </div>

      <manageServerModal.Provider>
        <MCPServerSetupModal
          server={null}
          onCompleted={(server) =>
            router.push(`${ADMIN_ROUTES.MCP_ACTIONS.path}/${server.id}`)
          }
          onTriggerFetchTools={triggerFetchToolsInPlace}
          mutateMcpServers={async () => {
            await mutateMcpServers();
          }}
        />
      </manageServerModal.Provider>
    </div>
  );
}
