"use client";

import { useMemo, useState } from "react";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ThreeDotsLoader } from "@/components/Loading";
import { Callout } from "@/components/ui/callout";
import { toast } from "@/hooks/useToast";
import { Button, Text } from "@opal/components";
import { Content } from "@opal/layouts";
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
import { useCloudSubscription } from "@/hooks/useCloudSubscription";
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

const API_KEY_SWR_KEY = "/api/admin/api-key";
const route = ADMIN_ROUTES.API_KEYS;

const tc = createTableColumns<APIKey>();

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ServiceAccountsPage() {
  const {
    data: apiKeys,
    isLoading,
    error,
  } = useSWR<APIKey[]>(API_KEY_SWR_KEY, errorHandlingFetcher);

  const canCreateKeys = useCloudSubscription();
  const { data: billingData } = useBillingInformation();
  const isTrialing =
    billingData !== undefined &&
    hasActiveSubscription(billingData) &&
    billingData.status === BillingStatus.TRIALING;

  const [fullApiKey, setFullApiKey] = useState<string | null>(null);
  const [keyIsGenerating, setKeyIsGenerating] = useState(false);
  const [showCreateUpdateForm, setShowCreateUpdateForm] = useState(false);
  const [selectedApiKey, setSelectedApiKey] = useState<APIKey | undefined>();
  const [search, setSearch] = useState("");
  const [regenerateTarget, setRegenerateTarget] = useState<APIKey | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<APIKey | null>(null);

  const filteredApiKeys = (apiKeys ?? [])
    .filter((key) => key.api_key_name !== DISCORD_SERVICE_API_KEY_NAME)
    .filter(
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
        toast.error(`Failed to update role: ${errorMsg}`);
        return;
      }
      mutate(API_KEY_SWR_KEY);
      toast.success("Role updated.");
    } catch {
      toast.error("Failed to update role.");
    }
  };

  const handleRegenerate = async (apiKey: APIKey) => {
    setKeyIsGenerating(true);
    try {
      const response = await regenerateApiKey(apiKey);
      if (!response.ok) {
        const errorMsg = await response.text();
        toast.error(`Failed to regenerate API Key: ${errorMsg}`);
        return;
      }
      const newKey = (await response.json()) as APIKey;
      setFullApiKey(newKey.api_key);
      mutate(API_KEY_SWR_KEY);
    } finally {
      setKeyIsGenerating(false);
    }
  };

  const handleDelete = async (apiKey: APIKey) => {
    const response = await deleteApiKey(apiKey.api_key_id);
    if (!response.ok) {
      const errorMsg = await response.text();
      toast.error(`Failed to delete API Key: ${errorMsg}`);
      return;
    }
    mutate(API_KEY_SWR_KEY);
  };

  const columns = useMemo(
    () => [
      tc.qualifier({
        content: "icon",
        getContent: () => SvgUserKey,
      }),
      tc.column("api_key_name", {
        header: "Name",
        weight: 25,
        cell: (value) => (
          <Content
            title={value || "Unnamed"}
            sizePreset="main-ui"
            variant="body"
          />
        ),
      }),
      tc.column("api_key_display", {
        header: "API Key",
        weight: 30,
        cell: (value) => (
          <Text font="secondary-mono" color="text-03">
            {value}
          </Text>
        ),
      }),
      tc.displayColumn({
        id: "account_type",
        header: "Account Type",
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
                description="Unrestricted admin access to all endpoints."
              >
                {USER_ROLE_LABELS[UserRole.ADMIN]}
              </InputSelect.Item>
              <InputSelect.Item
                value={UserRole.BASIC.toString()}
                icon={SvgUser}
                description="Standard user-level access to non-admin endpoints."
              >
                {USER_ROLE_LABELS[UserRole.BASIC]}
              </InputSelect.Item>
              <InputSelect.Item
                value={UserRole.LIMITED.toString()}
                icon={SvgLock}
                description="For agents: chat posting and read-only access to other endpoints."
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
              tooltip="Regenerate"
              onClick={() => setRegenerateTarget(row)}
            />
            <Popover>
              <Popover.Trigger asChild>
                <Button
                  icon={SvgMoreHorizontal}
                  prominence="tertiary"
                  tooltip="More"
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
                    Edit Account
                  </LineItem>
                  <LineItem
                    icon={SvgTrash}
                    danger
                    onClick={() => setDeleteTarget(row)}
                  >
                    Delete Account
                  </LineItem>
                </PopoverMenu>
              </Popover.Content>
            </Popover>
          </div>
        ),
      }),
    ],
    [] // eslint-disable-line react-hooks/exhaustive-deps
  );

  if (error) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          title={route.title}
          icon={route.icon}
          description="Use service accounts to programmatically access Onyx API."
          separator
        />
        <SettingsLayouts.Body>
          <Callout type="danger" title="Failed to fetch API Keys">
            {error?.info?.detail || error.toString()}
          </Callout>
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
          description="Use service accounts to programmatically access Onyx API."
          separator
        />
        <SettingsLayouts.Body>
          <ThreeDotsLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  const hasKeys = filteredApiKeys.length > 0;

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        title={route.title}
        icon={route.icon}
        description="Use service accounts to programmatically access Onyx API."
        separator
      />

      <SettingsLayouts.Body>
        {isTrialing && (
          <Message
            static
            warning
            close={false}
            className="w-full"
            text="Upgrade to a paid plan to create API keys."
            description="Trial accounts do not include API key access — purchase a paid subscription to unlock this feature."
          />
        )}

        <div className="flex flex-col">
          <AdminListHeader
            hasItems={hasKeys}
            searchQuery={search}
            onSearchQueryChange={setSearch}
            placeholder="Search service accounts..."
            emptyStateText="Create service account API keys with user-level access."
            onAction={() => {
              setSelectedApiKey(undefined);
              setShowCreateUpdateForm(true);
            }}
            actionLabel="New Service Account"
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
            title="Service Account API Key"
            icon={SvgKey}
            onClose={() => setFullApiKey(null)}
            description="Save this key before continuing. It won't be shown again."
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
                  Download
                </Button>
              }
              submit={
                <Button
                  onClick={() => {
                    if (fullApiKey) {
                      navigator.clipboard.writeText(fullApiKey);
                      toast.success("API key copied to clipboard.");
                    }
                  }}
                >
                  Copy API Key
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
          title="Regenerate API Key"
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
              Regenerate Key
            </Button>
          }
        >
          <Text as="p" color="text-03">
            {markdown(
              `Your current API key *${
                regenerateTarget.api_key_name || "Unnamed"
              }* (\`${
                regenerateTarget.api_key_display
              }\`) will be revoked and a new key will be generated. You will need to update any applications using this key with the new one.`
            )}
          </Text>
        </ConfirmationModalLayout>
      )}

      {deleteTarget && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete Account"
          onClose={() => setDeleteTarget(null)}
          submit={
            <Button
              variant="danger"
              onClick={async () => {
                await handleDelete(deleteTarget);
                setDeleteTarget(null);
              }}
            >
              Delete
            </Button>
          }
        >
          <Section alignItems="start" gap={0.5}>
            <Text as="p" color="text-03">
              {markdown(
                `Any application using the API key of account *${
                  deleteTarget.api_key_name || "Unnamed"
                }* (\`${
                  deleteTarget.api_key_display
                }\`) will lose access to Onyx.`
              )}
            </Text>
            <Text as="p" color="text-03">
              Deletion cannot be undone.
            </Text>
          </Section>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
