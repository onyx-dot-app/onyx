"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { SettingsLayouts, toast } from "@opal/layouts";
import {
  BasicModalFooter,
  Button,
  Code,
  LineItemButton,
  MessageCard,
  Modal,
  Popover,
  PopoverMenu,
  Table,
  Tag,
  Text,
} from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  SvgDownload,
  SvgKey,
  SvgMoreHorizontal,
  SvgRefreshCw,
  SvgTrash,
  SvgUserEdit,
  SvgUserKey,
  SvgUsers,
  SvgSimpleLoader,
} from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import AdminListHeader from "@/sections/admin/AdminListHeader";
import { ConfirmationModalLayout } from "@opal/layouts";
import { markdown } from "@opal/utils";

import { useBillingInformation } from "@/hooks/useBillingInformation";
import { BillingStatus, hasActiveSubscription } from "@/lib/billing/interfaces";
import {
  deleteApiKey,
  regenerateApiKey,
  updateApiKey,
} from "@/views/admin/ServiceAccountsPage/svc";
import type { APIKey } from "@/views/admin/ServiceAccountsPage/interfaces";
import { DISCORD_SERVICE_API_KEY_NAME } from "@/views/admin/ServiceAccountsPage/interfaces";
import ApiKeyFormModal from "@/views/admin/ServiceAccountsPage/ApiKeyFormModal";
import EditServiceAccountModal from "@/views/admin/ServiceAccountsPage/EditServiceAccountModal";
import { createTableColumns } from "@opal/components/table/columns";
import { Section } from "@/layouts/general-layouts";

const API_KEY_SWR_KEY = SWR_KEYS.adminApiKeys;
const route = ADMIN_ROUTES.API_KEYS;

const tc = createTableColumns<APIKey>();

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ServiceAccountsPage() {
  const t = useTranslations("admin.serviceAccounts");
  const {
    data: apiKeys,
    isLoading,
    error,
  } = useSWR<APIKey[]>(API_KEY_SWR_KEY, errorHandlingFetcher);

  const { data: billingData } = useBillingInformation();
  const isTrialing =
    billingData !== undefined &&
    hasActiveSubscription(billingData) &&
    billingData.status === BillingStatus.TRIALING;

  const [fullApiKey, setFullApiKey] = useState<string | null>(null);
  const [showCreateUpdateForm, setShowCreateUpdateForm] = useState(false);
  const [selectedApiKey, setSelectedApiKey] = useState<APIKey | undefined>();
  const [search, setSearch] = useState("");
  const [regenerateTarget, setRegenerateTarget] = useState<APIKey | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<APIKey | null>(null);
  const [groupsRolesTarget, setGroupsRolesTarget] = useState<APIKey | null>(
    null
  );

  const visibleApiKeys = (apiKeys ?? []).filter(
    (key) => key.api_key_name !== DISCORD_SERVICE_API_KEY_NAME
  );

  const filteredApiKeys = visibleApiKeys.filter(
    (key) =>
      !search ||
      (key.api_key_name ?? "").toLowerCase().includes(search.toLowerCase()) ||
      key.api_key_display.toLowerCase().includes(search.toLowerCase())
  );

  const handleRegenerate = async (apiKey: APIKey) => {
    try {
      const response = await regenerateApiKey(apiKey);
      if (!response.ok) {
        const errorMsg = await response.text();
        toast.error(
          t("toasts.regenerateFailedWithDetail", { detail: errorMsg })
        );
        return;
      }
      const newKey = (await response.json()) as APIKey;
      setFullApiKey(newKey.api_key);
      mutate(API_KEY_SWR_KEY);
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : t("toasts.regenerateFailed")
      );
    }
  };

  const handleDelete = async (apiKey: APIKey) => {
    try {
      const response = await deleteApiKey(apiKey.api_key_id);
      if (!response.ok) {
        const errorMsg = await response.text();
        toast.error(t("toasts.deleteFailedWithDetail", { detail: errorMsg }));
        return;
      }
      mutate(API_KEY_SWR_KEY);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("toasts.deleteFailed"));
    }
  };

  const columns = useMemo(
    () => [
      tc.qualifier({
        content: "icon",
        getContent: () => SvgUserKey,
      }),
      tc.column("api_key_name", {
        header: t("table.columns.name.header"),
        weight: 25,
        cell: (value) => (
          <Content
            title={value || t("table.name.unnamed")}
            sizePreset="main-ui"
            variant="body"
          />
        ),
      }),
      tc.column("api_key_display", {
        header: t("table.columns.apiKey.header"),
        weight: 30,
        cell: (value) => (
          <Text font="secondary-mono" color="text-03">
            {value}
          </Text>
        ),
      }),
      tc.displayColumn({
        id: "groups",
        header: t("table.columns.groups.header"),
        width: { weight: 25, minWidth: 160 },
        cell: (row) => {
          const groups = row.groups ?? [];
          if (groups.length === 0) {
            return (
              <Text font="secondary-body" color="text-03">
                —
              </Text>
            );
          }
          const maxVisible = 2;
          const visible = groups.slice(0, maxVisible);
          const overflow = groups.length - maxVisible;
          return (
            <div className="flex items-center gap-1 overflow-hidden flex-nowrap min-w-0">
              {visible.map((g) => (
                <Tag key={g.id} title={g.name} size="md" />
              ))}
              {overflow > 0 && (
                <Tag
                  title={t("table.groups.overflow.label", { count: overflow })}
                  size="md"
                />
              )}
            </div>
          );
        },
      }),
      tc.actions({
        cell: (row) => (
          <div className="flex flex-row gap-1">
            <Button
              icon={SvgRefreshCw}
              prominence="tertiary"
              tooltip={t("table.regenerateButton.tooltip")}
              onClick={() => setRegenerateTarget(row)}
            />
            <Popover>
              <Popover.Trigger asChild>
                <Button
                  icon={SvgMoreHorizontal}
                  prominence="tertiary"
                  tooltip={t("table.moreButton.tooltip")}
                />
              </Popover.Trigger>
              <Popover.Content side="bottom" align="end" width="md">
                <PopoverMenu>
                  <LineItemButton
                    sizePreset="main-ui"
                    rounding={2}
                    icon={SvgUsers}
                    onClick={() => setGroupsRolesTarget(row)}
                    title={t("table.actions.groups.label")}
                  />
                  <LineItemButton
                    sizePreset="main-ui"
                    rounding={2}
                    icon={SvgUserEdit}
                    onClick={() => {
                      setSelectedApiKey(row);
                      setShowCreateUpdateForm(true);
                    }}
                    title={t("table.actions.edit.label")}
                  />
                  <LineItemButton
                    sizePreset="main-ui"
                    rounding={2}
                    icon={SvgTrash}
                    color="danger"
                    onClick={() => setDeleteTarget(row)}
                    title={t("table.actions.delete.label")}
                  />
                </PopoverMenu>
              </Popover.Content>
            </Popover>
          </div>
        ),
      }),
    ],
    [t] // eslint-disable-line react-hooks/exhaustive-deps
  );

  if (error) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          title={route.title}
          icon={route.icon}
          description={t("page.description")}
          divider
        />
        <SettingsLayouts.Body>
          <IllustrationContent
            illustration={SvgNoResult}
            title={t("page.error.title")}
            description={t("page.error.description")}
          />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  if (isLoading) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          title={route.title}
          icon={route.icon}
          description={t("page.description")}
          divider
        />
        <SettingsLayouts.Body>
          <SvgSimpleLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  const hasKeys = visibleApiKeys.length > 0;

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        title={route.title}
        icon={route.icon}
        description={t("page.description")}
        divider
      />

      <SettingsLayouts.Body>
        {isTrialing && (
          <MessageCard
            variant="warning"
            title={t("trialNotice.title")}
            description={t("trialNotice.description")}
          />
        )}

        <div className="flex flex-col">
          <AdminListHeader
            hasItems={hasKeys}
            searchQuery={search}
            onSearchQueryChange={setSearch}
            placeholder={t("list.search.placeholder")}
            emptyStateText={t("list.empty.description")}
            onAction={() => {
              setSelectedApiKey(undefined);
              setShowCreateUpdateForm(true);
            }}
            actionLabel={t("list.createButton.label")}
          />

          {hasKeys && (
            <Table
              data={filteredApiKeys}
              getRowId={(row) => String(row.api_key_id)}
              columns={columns}
              searchTerm={search}
            />
          )}
        </div>
      </SettingsLayouts.Body>

      <Modal open={!!fullApiKey}>
        <Modal.Content width="sm" height="sm">
          <Modal.Header
            title={t("keyModal.title")}
            icon={SvgKey}
            onClose={() => setFullApiKey(null)}
            description={t("keyModal.description")}
          />
          <Modal.Body>
            <Code showCopyButton={false}>{fullApiKey ?? ""}</Code>
          </Modal.Body>
          <Modal.Footer>
            <BasicModalFooter
              left={
                <Button
                  prominence="secondary"
                  icon={SvgDownload}
                  onClick={() => {
                    if (!fullApiKey) return;
                    const blob = new Blob([fullApiKey], {
                      type: "text/plain",
                    });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = "onyx-api-key.txt";
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  {t("keyModal.downloadButton.label")}
                </Button>
              }
              submit={
                // TODO(@raunakab): Create an opalified copy-button and replace it here
                <Button
                  onClick={() => {
                    if (fullApiKey) {
                      navigator.clipboard.writeText(fullApiKey);
                      toast.success(t("toasts.keyCopied"));
                    }
                  }}
                >
                  {t("keyModal.copyButton.label")}
                </Button>
              }
            />
          </Modal.Footer>
        </Modal.Content>
      </Modal>

      {showCreateUpdateForm && (
        <ApiKeyFormModal
          onCreateApiKey={(apiKey) => {
            setFullApiKey(apiKey.api_key);
          }}
          onClose={() => {
            setShowCreateUpdateForm(false);
            setSelectedApiKey(undefined);
            mutate(API_KEY_SWR_KEY);
          }}
          apiKey={selectedApiKey}
        />
      )}

      {groupsRolesTarget && (
        <EditServiceAccountModal
          apiKey={groupsRolesTarget}
          onClose={() => setGroupsRolesTarget(null)}
          onMutate={() => mutate(API_KEY_SWR_KEY)}
        />
      )}

      {regenerateTarget && (
        <ConfirmationModalLayout
          icon={SvgRefreshCw}
          title={t("regenerateModal.title")}
          onClose={() => setRegenerateTarget(null)}
          submit={
            <Button
              variant="danger"
              onClick={async () => {
                const target = regenerateTarget;
                setRegenerateTarget(null);
                await handleRegenerate(target);
              }}
            >
              {t("regenerateModal.submit.label")}
            </Button>
          }
        >
          <Text as="p" color="text-03">
            {markdown(
              t("regenerateModal.description", {
                name: regenerateTarget.api_key_name || t("table.name.unnamed"),
                keyDisplay: regenerateTarget.api_key_display,
              })
            )}
          </Text>
        </ConfirmationModalLayout>
      )}

      {deleteTarget && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={t("deleteModal.title")}
          onClose={() => setDeleteTarget(null)}
          submit={
            <Button
              variant="danger"
              onClick={async () => {
                await handleDelete(deleteTarget);
                setDeleteTarget(null);
              }}
            >
              {t("deleteModal.submit.label")}
            </Button>
          }
        >
          <Section alignItems="start" gap={2}>
            <Text as="p" color="text-03">
              {markdown(
                t("deleteModal.description", {
                  name: deleteTarget.api_key_name || t("table.name.unnamed"),
                  keyDisplay: deleteTarget.api_key_display,
                })
              )}
            </Text>
            <Text as="p" color="text-03">
              {t("deleteModal.warning")}
            </Text>
          </Section>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
