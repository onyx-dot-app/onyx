"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useSearchParams } from "next/navigation";
import AdminListHeader from "@/sections/admin/AdminListHeader";
import OpenApiActionCard from "@/sections/actions/OpenApiActionCard";
import ActionCardSkeleton from "@/sections/actions/skeleton/ActionCardSkeleton";
import OpenApiActionDialogs from "@/sections/actions/OpenApiActionDialogs";
import useOpenApiTools from "@/hooks/useOpenApiTools";

export default function OpenApiPageContent() {
  const t = useTranslations("actions");
  const { mutate } = useSWRConfig();
  const {
    openApiTools,
    mutateOpenApiTools,
    isLoading: isOpenApiLoading,
  } = useOpenApiTools();
  const requestedToolId = useSearchParams().get("toolId");
  const [searchQuery, setSearchQuery] = useState("");
  // Filter tools based on search query
  const filteredTools = useMemo(() => {
    if (!openApiTools) return [];
    if (!searchQuery.trim()) return openApiTools;

    const query = searchQuery.toLowerCase();
    return openApiTools.filter(
      (tool) =>
        tool.name.toLowerCase().includes(query) ||
        tool.description?.toLowerCase().includes(query)
    );
  }, [openApiTools, searchQuery]);

  return (
    <OpenApiActionDialogs
      initialTool={openApiTools?.find(
        (tool) => tool.id === Number(requestedToolId)
      )}
      onChanged={async () => {
        await Promise.all([
          mutateOpenApiTools(),
          mutate(SWR_KEYS.buildExternalAppsAdmin),
        ]);
      }}
    >
      {(actions) => (
        <div className="flex flex-col h-full overflow-hidden">
          <div className="shrink-0 mb-4">
            <AdminListHeader
              hasItems={isOpenApiLoading || (openApiTools?.length ?? 0) > 0}
              searchQuery={searchQuery}
              onSearchQueryChange={setSearchQuery}
              onAction={actions.add}
              actionLabel={t("openApiPage.addButton.label")}
              emptyStateText={t("openApiPage.empty.description")}
            />
          </div>

          <div className="flex-1 overflow-y-auto min-h-0">
            <div className="flex flex-col gap-4 w-full pb-4">
              {isOpenApiLoading ? (
                <>
                  <ActionCardSkeleton />
                  <ActionCardSkeleton />
                </>
              ) : (
                filteredTools.map((tool) => (
                  <OpenApiActionCard
                    key={tool.id}
                    tool={tool}
                    onAuthenticate={actions.authenticate}
                    onManage={actions.manage}
                    onDelete={actions.delete}
                    onRename={actions.rename}
                    mutateOpenApiTools={async () => {
                      await mutateOpenApiTools();
                    }}
                    onOpenDisconnectModal={actions.disconnect}
                  />
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </OpenApiActionDialogs>
  );
}
