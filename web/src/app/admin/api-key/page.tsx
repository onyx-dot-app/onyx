"use client";

import { ThreeDotsLoader } from "@/components/Loading";
import { errorHandlingFetcher } from "@/lib/fetcher";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ErrorCallout } from "@/components/ErrorCallout";
import useSWR, { mutate } from "swr";
import Separator from "@/refresh-components/Separator";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Table,
} from "@/components/ui/table";
import Title from "@/components/ui/title";
import { toast } from "@/hooks/useToast";
import { useState } from "react";
import { DeleteButton } from "@/components/DeleteButton";
import Modal from "@/refresh-components/Modal";
import { Spinner } from "@/components/Spinner";
import { deleteApiKey, regenerateApiKey } from "@/app/admin/api-key/lib";
import OnyxApiKeyForm from "@/app/admin/api-key/OnyxApiKeyForm";
import {
  APIKey,
  DISCORD_SERVICE_API_KEY_NAME,
} from "@/app/admin/api-key/types";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import { Button } from "@opal/components";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
// TODO(@raunakab): migrate this `refresh-components/Text` to `@opal/components` Text
import Text from "@/refresh-components/texts/Text";
import { SvgEdit, SvgInfo, SvgKey, SvgRefreshCw } from "@opal/icons";
import { useCloudSubscription } from "@/hooks/useCloudSubscription";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.API_KEYS;

function Main() {
  const {
    data: apiKeys,
    isLoading,
    error,
  } = useSWR<APIKey[]>("/api/admin/api-key", errorHandlingFetcher);

  const canCreateKeys = useCloudSubscription();

  const [fullApiKey, setFullApiKey] = useState<string | null>(null);
  const [keyIsGenerating, setKeyIsGenerating] = useState(false);
  const [showCreateUpdateForm, setShowCreateUpdateForm] = useState(false);
  const [selectedApiKey, setSelectedApiKey] = useState<APIKey | undefined>();

  const handleEdit = (apiKey: APIKey) => {
    setSelectedApiKey(apiKey);
    setShowCreateUpdateForm(true);
  };

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (!apiKeys || error) {
    return (
      <ErrorCallout
        errorTitle="Failed to fetch API Keys"
        errorMsg={error?.info?.detail || error.toString()}
      />
    );
  }

  // Filter out the discord service key from the displayed list
  const filteredApiKeys = apiKeys.filter(
    (key) => key.api_key_name !== DISCORD_SERVICE_API_KEY_NAME
  );

  const introSection = (
    <div className="flex flex-col items-start gap-4">
      <Text as="p">
        API Keys allow you to access Onyx APIs programmatically.
        {canCreateKeys
          ? " Click the button below to generate a new API Key."
          : ""}
      </Text>
      {canCreateKeys ? (
        <CreateButton onClick={() => setShowCreateUpdateForm(true)}>
          Create API Key
        </CreateButton>
      ) : (
        <div className="flex flex-col gap-2 rounded-lg bg-background-tint-02 p-4">
          <div className="flex items-center gap-1.5">
            <Text as="p" text04>
              Upgrade to a paid plan to create API keys.
            </Text>
            <Button
              variant="none"
              prominence="tertiary"
              size="2xs"
              icon={SvgInfo}
              tooltip="API keys enable programmatic access to Onyx for service accounts and integrations. Trial accounts do not include API key access — purchase a paid subscription to unlock this feature."
            />
          </div>
          <Button href="/admin/billing">Upgrade to Paid Plan</Button>
        </div>
      )}
    </div>
  );

  if (filteredApiKeys.length === 0) {
    return (
      <div>
        {introSection}

        {showCreateUpdateForm && (
          <OnyxApiKeyForm
            onCreateApiKey={(apiKey) => {
              setFullApiKey(apiKey.api_key);
            }}
            onClose={() => {
              setShowCreateUpdateForm(false);
              setSelectedApiKey(undefined);
              mutate("/api/admin/api-key");
            }}
            apiKey={selectedApiKey}
          />
        )}
      </div>
    );
  }

  return (
    <>
      <Modal open={!!fullApiKey}>
        <Modal.Content width="sm" height="sm">
          <Modal.Header
            title="New API Key"
            icon={SvgKey}
            onClose={() => setFullApiKey(null)}
            description="Make sure you copy your new API key. You won't be able to see this key again."
          />
          <Modal.Body>
            <Text as="p" className="break-all flex-1">
              {fullApiKey}
            </Text>
            <CopyIconButton getCopyText={() => fullApiKey!} />
          </Modal.Body>
        </Modal.Content>
      </Modal>

      {keyIsGenerating && <Spinner />}

      {introSection}

      {canCreateKeys && (
        <>
          <Separator />

          <Title className="mt-6">Existing API Keys</Title>
          <Table className="overflow-visible">
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>API Key</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Regenerate</TableHead>
                <TableHead>Delete</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredApiKeys.map((apiKey) => (
                <TableRow key={apiKey.api_key_id}>
                  <TableCell>
                    <Button
                      prominence="internal"
                      onClick={() => handleEdit(apiKey)}
                      icon={SvgEdit}
                    >
                      {apiKey.api_key_name || "null"}
                    </Button>
                  </TableCell>
                  <TableCell className="max-w-64">
                    {apiKey.api_key_display}
                  </TableCell>
                  <TableCell className="max-w-64">
                    {apiKey.api_key_role.toUpperCase()}
                  </TableCell>
                  <TableCell>
                    <Button
                      prominence="internal"
                      icon={SvgRefreshCw}
                      onClick={async () => {
                        setKeyIsGenerating(true);
                        const response = await regenerateApiKey(apiKey);
                        setKeyIsGenerating(false);
                        if (!response.ok) {
                          const errorMsg = await response.text();
                          toast.error(
                            `Failed to regenerate API Key: ${errorMsg}`
                          );
                          return;
                        }
                        const newKey = (await response.json()) as APIKey;
                        setFullApiKey(newKey.api_key);
                        mutate("/api/admin/api-key");
                      }}
                    >
                      Refresh
                    </Button>
                  </TableCell>
                  <TableCell>
                    <DeleteButton
                      onClick={async () => {
                        const response = await deleteApiKey(apiKey.api_key_id);
                        if (!response.ok) {
                          const errorMsg = await response.text();
                          toast.error(`Failed to delete API Key: ${errorMsg}`);
                          return;
                        }
                        mutate("/api/admin/api-key");
                      }}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {showCreateUpdateForm && (
            <OnyxApiKeyForm
              onCreateApiKey={(apiKey) => {
                setFullApiKey(apiKey.api_key);
              }}
              onClose={() => {
                setShowCreateUpdateForm(false);
                setSelectedApiKey(undefined);
                mutate("/api/admin/api-key");
              }}
              apiKey={selectedApiKey}
            />
          )}
        </>
      )}
    </>
  );
}

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header title={route.title} icon={route.icon} separator />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
