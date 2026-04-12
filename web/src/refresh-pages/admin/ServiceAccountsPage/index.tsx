"use client";

import { useMemo, useState } from "react";
import useSWR, { mutate } from "swr";
import { useTranslations } from "next-intl";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { toast } from "@/hooks/useToast";
import { Button, Text } from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  SvgDownload,
  SvgKey,
  SvgLock,
  SvgMoreHorizontal,
  SvgRefreshCw,
  SvgTrash,
  SvgUser,
  SvgUserEdit,
  SvgUserKey,
  SvgUserManage,
} from "@opal/icons";
import { USER_ROLE_LABELS, UserRole } from "@/lib/types";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import AdminListHeader from "@/sections/admin/AdminListHeader";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import Code from "@/refresh-components/Code";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { markdown } from "@opal/utils";
import Message from "@/refresh-components/messages/Message";

import { useBillingInformation } from "@/hooks/useBillingInformation";
import { BillingStatus, hasActiveSubscription } from "@/lib/billing/interfaces";
import {
  deleteApiKey,
  regenerateApiKey,
  updateApiKey,
} from "@/refresh-pages/admin/ServiceAccountsPage/svc";
import type { APIKey } from "@/refresh-pages/admin/ServiceAccountsPage/interfaces";
import { DISCORD_SERVICE_API_KEY_NAME } from "@/refresh-pages/admin/ServiceAccountsPage/interfaces";
import ApiKeyFormModal from "@/refresh-pages/admin/ServiceAccountsPage/ApiKeyFormModal";
import { Table } from "@opal/components";
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

  const visibleApiKeys = (apiKeys ?? []).filter(
    (key) => key.api_key_name !== DISCORD_SERVICE_API_KEY_NAME
  );

  const filteredApiKeys = visibleApiKeys.filter(
    (key) =>
      !search ||
      (key.api_key_name ?? "").toLowerCase().includes(search.toLowerCase()) ||
      key.api_key_display.toLowerCase().includes(search.toLowerCase())
  );

  const handleRoleChange = async (apiKey: APIKey, newRole: UserRole) => {
    try {
      const response = await updateApiKey(apiKey.api_key_id, {
        name: apiKey.api_key_name ?? undefined,
        role: newRole,
      });
      if (!response.ok) {
        const errorMsg = await response.text();
        toast.error(t("toast.roleUpdateFailed"));
        return;
      }
      mutate(API_KEY_SWR_KEY);
      toast.success(t("toast.roleUpdated"));
    } catch {
      toast.error(t("toast.roleUpdateFailed"));
    }
  };

  const handleRegenerate = async (apiKey: APIKey) => {
    try {
      const response = await regenerateApiKey(apiKey);
      if (!response.ok) {
        const errorMsg = await response.text();
        toast.error(t("toast.regenerateFailed", { error: errorMsg }));
        return;
      }
      const newKey = (await response.json()) as APIKey;
      setFullApiKey(newKey.api_key);
      mutate(API_KEY_SWR_KEY);
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : t("toast.regenerateFailed", { error: "" })
      );
    }
  };

  const handleDelete = async (apiKey: APIKey) => {
    try {
      const response = await deleteApiKey(apiKey.api_key_id);
      if (!response.ok) {
        const errorMsg = await response.text();
        toast.error(t("toast.deleteFailed", { error: errorMsg }));
        return;
      }
      mutate(API_KEY_SWR_KEY);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("toast.deleteFailed", { error: "" }));
    }
  };

  const columns = useMemo(
    () => [
      tc.qualifier({
        content: "icon",
        getContent: () => SvgUserKey,
      }),
      tc.column("api_key_name", {
        header: t("nameCol"),
        weight: 25,
        cell: (value) => (
          <Content
            title={value || t("unnamed")}
            sizePreset="main-ui"
            variant="body"
          />
        ),
      }),
      tc.column("api_key_display", {
        header: t("apiKeyCol"),
        weight: 30,
        cell: (value) => (
          <Text font="secondary-mono" color="text-03">
            {value}
          </Text>
        ),
      }),
      tc.displayColumn({
        id: "account_type",
        header: t("accountTypeCol"),
        width: { weight: 25, minWidth: 160 },
        cell: (row) => (
          <InputSelect
            value={row.api_key_role}
            onValueChange={(value) => handleRoleChange(row, value as UserRole)}
          >
            <InputSelect.Trigger />
            <InputSelect.Content>
              <InputSelect.Item
                value={UserRole.ADMIN.toString()}
                icon={SvgUserManage}
                description={t("adminRoleDescription")}
              >
                {USER_ROLE_LABELS[UserRole.ADMIN]}
              </InputSelect.Item>
              <InputSelect.Item
                value={UserRole.BASIC.toString()}
                icon={SvgUser}
                description={t("basicRoleDescription")}
              >
                {USER_ROLE_LABELS[UserRole.BASIC]}
              </InputSelect.Item>
              <InputSelect.Item
                value={UserRole.LIMITED.toString()}
                icon={SvgLock}
                description={t("limitedRoleDescription")}
              >
                {USER_ROLE_LABELS[UserRole.LIMITED]}
              </InputSelect.Item>
            </InputSelect.Content>
          </InputSelect>
        ),
      }),
      tc.actions({
        cell: (row) => (
          <div className="flex flex-row gap-1">
            <Button
              icon={SvgRefreshCw}
              prominence="tertiary"
              tooltip={t("regenerate")}
              onClick={() => setRegenerateTarget(row)}
            />
            <Popover>
              <Popover.Trigger asChild>
                <Button
                  icon={SvgMoreHorizontal}
                  prominence="tertiary"
                  tooltip={t("more")}
                />
              </Popover.Trigger>
              <Popover.Content side="bottom" align="end" width="md">
                <PopoverMenu>
                  <LineItem
                    icon={SvgUserEdit}
                    onClick={() => {
                      setSelectedApiKey(row);
                      setShowCreateUpdateForm(true);
                    }}
                  >
                    {t("editAccount")}
                  </LineItem>
                  <LineItem
                    icon={SvgTrash}
                    danger
                    onClick={() => setDeleteTarget(row)}
                  >
                    {t("deleteAccountLabel")}
                  </LineItem>
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
          description={t("description")}
          separator
        />
        <SettingsLayouts.Body>
          <IllustrationContent
            illustration={SvgNoResult}
            title={t("failedToLoad")}
            description={t("checkConsoleDetails")}
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
          description={t("description")}
          separator
        />
        <SettingsLayouts.Body>
          <SimpleLoader />
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
        description={t("description")}
        separator
      />

      <SettingsLayouts.Body>
        {isTrialing && (
          <Message
            static
            warning
            close={false}
            className="w-full"
            text={t("upgradePlan")}
            description={t("upgradePlanDescription")}
          />
        )}

        <div className="flex flex-col">
          <AdminListHeader
            hasItems={hasKeys}
            searchQuery={search}
            onSearchQueryChange={setSearch}
            placeholder={t("searchPlaceholder")}
            emptyStateText={t("emptyStateText")}
            onAction={() => {
              setSelectedApiKey(undefined);
              setShowCreateUpdateForm(true);
            }}
            actionLabel={t("newServiceAccount")}
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
            title={t("apiKeyModalTitle")}
            icon={SvgKey}
            onClose={() => setFullApiKey(null)}
            description={t("apiKeyModalDescription")}
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
                  {t("download")}
                </Button>
              }
              submit={
                // TODO(@raunakab): Create an opalified copy-button and replace it here
                <Button
                  onClick={() => {
                    if (fullApiKey) {
                      navigator.clipboard.writeText(fullApiKey);
                      toast.success(t("toast.apiKeyCopied"));
                    }
                  }}
                >
                  {t("copyApiKey")}
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

      {regenerateTarget && (
        <ConfirmationModalLayout
          icon={SvgRefreshCw}
          title={t("regenerateTitle")}
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
              {t("regenerateKey")}
            </Button>
          }
        >
          <Text as="p" color="text-03">
            {markdown(
              t("regenerateDescription", {
                name: regenerateTarget.api_key_name || t("unnamed"),
                display: regenerateTarget.api_key_display,
              })
            )}
          </Text>
        </ConfirmationModalLayout>
      )}

      {deleteTarget && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={t("deleteTitle")}
          onClose={() => setDeleteTarget(null)}
          submit={
            <Button
              variant="danger"
              onClick={async () => {
                await handleDelete(deleteTarget);
                setDeleteTarget(null);
              }}
            >
              {t("deleteAccountLabel")}
            </Button>
          }
        >
          <Section alignItems="start" gap={0.5}>
            <Text as="p" color="text-03">
              {markdown(
                t("deleteAccountDescription", {
                  name: deleteTarget.api_key_name || t("unnamed"),
                  display: deleteTarget.api_key_display,
                })
              )}
            </Text>
            <Text as="p" color="text-03">
              {t("deletionCannotBeUndone")}
            </Text>
          </Section>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
