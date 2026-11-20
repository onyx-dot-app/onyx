"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  type DropdownMenuItem,
  MessageCard,
  Table,
  Text,
  type TableColumn,
  useCreateModal,
} from "@opal/components";
import { Content, IllustrationContent, Section, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import {
  SvgMoreHorizontal,
  SvgRefreshCw,
  SvgTrash,
  SvgUserSync,
  SvgUsers,
} from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import SvgNoResult from "@opal/illustrations/no-result";
import { fetchErrorDetail } from "@/lib/fetcher";
import {
  replaceMarketplaceLogin,
  syncMarketplace,
} from "@/lib/marketplaces/api";
import useScreenSize from "@/hooks/useScreenSize";
import { useMarketplaces } from "@/lib/marketplaces/hooks";
import type {
  MarketplaceDetail,
  MarketplaceSummary,
} from "@/lib/marketplaces/types";
import {
  marketplaceSource,
  marketplaceSyncState,
} from "@/lib/marketplaces/utils";
import MarketplaceDefaultAccessModal from "@/sections/marketplaces/MarketplaceDefaultAccessModal";
import MarketplaceDetailModal from "@/sections/marketplaces/MarketplaceDetailModal";
import MarketplaceSyncStatus, {
  SYNC_STATE_COLOR,
} from "@/sections/marketplaces/MarketplaceSyncStatus";
import RemoveMarketplaceModal from "@/sections/marketplaces/RemoveMarketplaceModal";

interface AttentionProps {
  marketplaces: MarketplaceSummary[];
  busy: ReadonlySet<string>;
  onSync: (marketplace: MarketplaceSummary) => void;
}

function Attention({ marketplaces, busy, onSync }: AttentionProps) {
  const t = useTranslations("plugins.marketplaces.attention");
  const syncCopy = useTranslations("plugins.marketplaces.sync");
  return (
    <>
      {marketplaces.map((row) => (
        <MessageCard
          key={row.id}
          variant="error"
          outerPadding={1}
          innerPadding={1}
          title={t("failedTitle", { name: row.name })}
          description={row.last_error ?? undefined}
          rightChildren={
            <Button
              prominence="secondary"
              size="sm"
              icon={SvgRefreshCw}
              disabled={busy.has(row.id)}
              onClick={() => onSync(row)}
            >
              {syncCopy("now")}
            </Button>
          }
        />
      ))}
    </>
  );
}

export default function MarketplacesTable() {
  const t = useTranslations("plugins.marketplaces");
  const { marketplaces, error, isLoading, refresh } = useMarketplaces();
  const { isMobile } = useScreenSize();
  const [openId, setOpenId] = useState<string | null>(null);
  const [defaultTarget, setDefaultTarget] = useState<MarketplaceSummary | null>(
    null
  );
  const [removeTarget, setRemoveTarget] = useState<MarketplaceSummary | null>(
    null
  );
  const removeModal = useCreateModal();
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());

  async function act(
    row: MarketplaceSummary,
    call: (id: string) => Promise<MarketplaceDetail>,
    success: string,
    failure: string,
    warning?: (detail: MarketplaceDetail) => string | null
  ) {
    setBusy((current) => new Set(current).add(row.id));
    try {
      const detail = await call(row.id);
      await refresh();
      const caution = warning?.(detail) ?? null;
      if (caution) toast.warning(caution);
      else toast.success(success);
    } catch (caught) {
      toast.error(fetchErrorDetail(caught) ?? failure);
    } finally {
      setBusy((current) => {
        const next = new Set(current);
        next.delete(row.id);
        return next;
      });
    }
  }

  function syncNow(row: MarketplaceSummary) {
    void act(
      row,
      syncMarketplace,
      t("sync.requested", { name: row.name }),
      t("sync.failed")
    );
  }

  function menu(row: MarketplaceSummary): DropdownMenuItem[] {
    const disabled = busy.has(row.id);
    return [
      {
        kind: "group",
        items: [
          {
            kind: "action",
            id: "sync",
            icon: SvgRefreshCw,
            title: t("sync.now"),
            disabled: disabled || row.syncing,
            onSelect: () => syncNow(row),
          },
          ...(row.scope === "company"
            ? [
                {
                  kind: "action" as const,
                  id: "default-access",
                  icon: SvgUsers,
                  title: t("defaultAccess.title"),
                  disabled,
                  onSelect: () => setDefaultTarget(row),
                },
              ]
            : []),
          {
            kind: "action",
            id: "replace-login",
            icon: SvgUserSync,
            title: t("replaceLogin.label"),
            description: t("replaceLogin.description"),
            disabled,
            onSelect: () =>
              void act(
                row,
                replaceMarketplaceLogin,
                t("replaceLogin.done", { name: row.name }),
                t("replaceLogin.failed"),
                (detail) =>
                  detail.login_has_github
                    ? null
                    : t("replaceLogin.doneWithoutGithub", { name: row.name })
              ),
          },
        ],
      },
      {
        kind: "group",
        items: [
          {
            kind: "action",
            id: "remove",
            icon: SvgTrash,
            title: t("remove.label"),
            danger: true,
            disabled,
            onSelect: () => {
              setRemoveTarget(row);
              removeModal.toggle(true);
            },
          },
        ],
      },
    ];
  }

  const nameCell = (row: MarketplaceSummary) => (
    <Content
      title={row.name}
      titleMaxLines={1}
      description={marketplaceSource(row)}
      descriptionMaxLines={1}
      badge={{ title: t(`scope.${row.scope}`) }}
    />
  );
  const actionsColumn: TableColumn<MarketplaceSummary> = {
    kind: "actions",
    showColumnVisibility: false,
    showSorting: false,
    cell: (row) =>
      row.can_manage ? (
        <Dropdown align="end">
          <Dropdown.Trigger asChild>
            <Button
              prominence="tertiary"
              size="sm"
              icon={SvgMoreHorizontal}
              aria-label={t("menu", { name: row.name })}
              tooltip={t("menu", { name: row.name })}
            />
          </Dropdown.Trigger>
          <Dropdown.Data
            label={t("menu", { name: row.name })}
            items={menu(row)}
          />
        </Dropdown>
      ) : null,
  };
  // A phone has no room for four columns: one stacked cell and the menu.
  const phoneColumns: TableColumn<MarketplaceSummary>[] = [
    {
      kind: "data",
      field: "name",
      title: t("columns.marketplace"),
      weight: 100,
      cell: (_name, row) => (
        <Content
          title={row.name}
          titleMaxLines={1}
          description={`${marketplaceSource(row)} · ${t("items", {
            count: row.plugin_count,
          })}`}
          descriptionMaxLines={1}
          badge={{
            title: t(`sync.state.${marketplaceSyncState(row)}`),
            color: SYNC_STATE_COLOR[marketplaceSyncState(row)],
          }}
        />
      ),
    },
    actionsColumn,
  ];
  const columns: TableColumn<MarketplaceSummary>[] = [
    { kind: "qualifier", content: "icon", icon: () => SvgGitHub },
    {
      kind: "data",
      field: "name",
      title: t("columns.marketplace"),
      weight: 40,
      cell: (_name, row) => nameCell(row),
    },
    {
      kind: "display",
      id: "sync",
      title: t("columns.sync"),
      width: { weight: 40 },
      cell: (row) => <MarketplaceSyncStatus marketplace={row} />,
    },
    {
      kind: "data",
      field: "plugin_count",
      title: t("columns.items"),
      weight: 14,
      cell: (count) => (
        <Text font="main-ui-body" color="text-03">
          {t("items", { count })}
        </Text>
      ),
    },
    actionsColumn,
  ];

  if (isLoading)
    return (
      <Section height="auto" className="min-h-20">
        <IconLoader />
      </Section>
    );
  if (error)
    return (
      <MessageCard
        variant="error"
        outerPadding={1}
        innerPadding={1}
        title={t("loadFailed")}
        description={fetchErrorDetail(error) ?? undefined}
      />
    );
  const rows = marketplaces ?? [];
  const attention = rows.filter(
    (row) => row.can_manage && marketplaceSyncState(row) === "failed"
  );
  return (
    <Section gap={2} alignItems="stretch" height="auto">
      <Attention marketplaces={attention} busy={busy} onSync={syncNow} />
      {rows.length > 0 ? (
        <Table
          label={t("tableLabel")}
          items={rows}
          columns={isMobile ? phoneColumns : columns}
          getRowId={(row) => row.id}
          pageSize={false}
          onRowClick={(row) => setOpenId(row.id)}
          getRowLabel={(row) => t("open", { name: row.name })}
        />
      ) : (
        <IllustrationContent
          illustration={SvgNoResult}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      )}
      {openId && (
        <MarketplaceDetailModal
          marketplaceId={openId}
          onClose={() => setOpenId(null)}
          onChanged={() => void refresh()}
        />
      )}
      {defaultTarget && (
        <MarketplaceDefaultAccessModal
          marketplace={defaultTarget}
          onClose={() => setDefaultTarget(null)}
          onSaved={() => {
            setDefaultTarget(null);
            void refresh();
          }}
        />
      )}
      <removeModal.Provider>
        {removeTarget && (
          <RemoveMarketplaceModal
            marketplace={removeTarget}
            onClose={() => removeModal.toggle(false)}
            onRemoved={() => {
              removeModal.toggle(false);
              setRemoveTarget(null);
              void refresh();
            }}
          />
        )}
      </removeModal.Provider>
    </Section>
  );
}
