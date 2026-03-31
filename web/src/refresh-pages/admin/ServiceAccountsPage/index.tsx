"use client";

import { useState } from "react";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ThreeDotsLoader } from "@/components/Loading";
import { Callout } from "@/components/ui/callout";
import { toast } from "@/hooks/useToast";
import { Button, Text } from "@opal/components";
import { Card } from "@opal/components";
import { Content } from "@opal/layouts";
import {
  SvgDownload,
  SvgKey,
  SvgMoreHorizontal,
  SvgPlusCircle,
  SvgRefreshCw,
  SvgUserKey,
} from "@opal/icons";
import { USER_ROLE_LABELS, UserRole } from "@/lib/types";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import Code from "@/refresh-components/Code";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const API_KEY_SWR_KEY = "/api/admin/api-key";
const route = ADMIN_ROUTES.API_KEYS;

// ---------------------------------------------------------------------------
// NewServiceAccountButton
// ---------------------------------------------------------------------------

function NewServiceAccountButton({ onClick }: { onClick: () => void }) {
  return (
    <Button rightIcon={SvgPlusCircle} onClick={onClick}>
      New Service Account
    </Button>
  );
}

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

  if (error) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          title={route.title}
          icon={route.icon}
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
      <SettingsLayouts.Header title={route.title} icon={route.icon} separator />

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

        {hasKeys ? (
          <>
            <div className="flex flex-row gap-3">
              <InputTypeIn
                leftSearchIcon
                placeholder="Search service accounts..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                showClearButton={false}
              />
              {canCreateKeys && (
                <NewServiceAccountButton
                  onClick={() => {
                    setSelectedApiKey(undefined);
                    setShowCreateUpdateForm(true);
                  }}
                />
              )}
              {!canCreateKeys && isTrialing && (
                <Button href="/admin/billing">Upgrade to Paid Plan</Button>
              )}
            </div>

            <Table className="overflow-visible">
              <TableHeader>
                <TableRow>
                  <TableHead />
                  <TableHead>Name</TableHead>
                  <TableHead>API Key</TableHead>
                  <TableHead>Account Type</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredApiKeys.map((apiKey) => (
                  <TableRow key={apiKey.api_key_id}>
                    <TableCell>
                      <SvgUserKey size={16} className="text-text-03" />
                    </TableCell>
                    <TableCell>{apiKey.api_key_name || "Unnamed"}</TableCell>
                    <TableCell className="max-w-64">
                      <Text font="secondary-body" color="text-03">
                        {apiKey.api_key_display}
                      </Text>
                    </TableCell>
                    <TableCell>
                      <InputSelect
                        value={apiKey.api_key_role}
                        onValueChange={(value) =>
                          handleRoleChange(apiKey, value as UserRole)
                        }
                      >
                        <InputSelect.Trigger />
                        <InputSelect.Content>
                          <InputSelect.Item value={UserRole.LIMITED.toString()}>
                            {USER_ROLE_LABELS[UserRole.LIMITED]}
                          </InputSelect.Item>
                          <InputSelect.Item value={UserRole.BASIC.toString()}>
                            {USER_ROLE_LABELS[UserRole.BASIC]}
                          </InputSelect.Item>
                          <InputSelect.Item value={UserRole.ADMIN.toString()}>
                            {USER_ROLE_LABELS[UserRole.ADMIN]}
                          </InputSelect.Item>
                        </InputSelect.Content>
                      </InputSelect>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-row gap-1">
                        <Button
                          icon={SvgRefreshCw}
                          prominence="tertiary"
                          tooltip="Regenerate"
                          onClick={() => handleRegenerate(apiKey)}
                        />
                        <Button
                          icon={SvgMoreHorizontal}
                          prominence="tertiary"
                          tooltip="More"
                          onClick={() => {
                            setSelectedApiKey(apiKey);
                            setShowCreateUpdateForm(true);
                          }}
                        />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        ) : (
          <Card
            paddingVariant="md"
            roundingVariant="lg"
            backgroundVariant="light"
            borderVariant="solid"
          >
            <div className="flex flex-row items-center justify-between gap-3">
              <Content
                title="Create service account API keys with user-level access."
                sizePreset="main-ui"
                variant="body"
                prominence="muted"
                widthVariant="fit"
              />
              {canCreateKeys ? (
                <NewServiceAccountButton
                  onClick={() => {
                    setSelectedApiKey(undefined);
                    setShowCreateUpdateForm(true);
                  }}
                />
              ) : isTrialing ? (
                <Button href="/admin/billing">Upgrade to Paid Plan</Button>
              ) : undefined}
            </div>
          </Card>
        )}
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
    </SettingsLayouts.Root>
  );
}
