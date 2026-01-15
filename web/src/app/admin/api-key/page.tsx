"use client";

import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { errorHandlingFetcher } from "@/lib/fetcher";
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
import { usePopup } from "@/components/admin/connectors/Popup";
import { useState } from "react";
import { DeleteButton } from "@/components/DeleteButton";
import Modal from "@/refresh-components/Modal";
import { Spinner } from "@/components/Spinner";
import { deleteApiKey, regenerateApiKey } from "@/app/admin/api-key/lib";
import OnyxApiKeyForm from "@/app/admin/api-key/OnyxApiKeyForm";
import { APIKey } from "@/app/admin/api-key/types";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import Button from "@/refresh-components/buttons/Button";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import Text from "@/refresh-components/texts/Text";
import { SvgEdit, SvgKey, SvgRefreshCw } from "@opal/icons";

function Main() {
  const { popup, setPopup } = usePopup();

  const {
    data: apiKeys,
    isLoading,
    error,
  } = useSWR<APIKey[]>("/api/admin/api-key", errorHandlingFetcher);

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

  const introSection = (
    <div className="flex flex-col items-start gap-4">
      <Text as="p">
        API Keys allow you to access Onyx APIs programmatically. Click the
        button below to generate a new API Key.
      </Text>
      <CreateButton
        className="self-start"
        onClick={() => setShowCreateUpdateForm(true)}
      >
        Create API Key
      </CreateButton>
    </div>
  );

  if (apiKeys.length === 0) {
    return (
      <div>
        {popup}
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
            setPopup={setPopup}
            apiKey={selectedApiKey}
          />
        )}
      </div>
    );
  }

  return (
    <>
      {popup}

      <Modal open={!!fullApiKey}>
        <Modal.Content small>
          <Modal.Header
            title="New API Key"
            icon={SvgKey}
            onClose={() => setFullApiKey(null)}
            description="Make sure you copy your new API key. You won’t be able to see this key again."
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
          {apiKeys.map((apiKey) => (
            <TableRow key={apiKey.api_key_id}>
              <TableCell>
                <Button
                  internal
                  onClick={() => handleEdit(apiKey)}
                  leftIcon={SvgEdit}
                >
                  {apiKey.api_key_name || <i>null</i>}
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
                  internal
                  leftIcon={SvgRefreshCw}
                  onClick={async () => {
                    setKeyIsGenerating(true);
                    const response = await regenerateApiKey(apiKey);
                    setKeyIsGenerating(false);
                    if (!response.ok) {
                      const errorMsg = await response.text();
                      setPopup({
                        type: "error",
                        message: `Failed to regenerate API Key: ${errorMsg}`,
                      });
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
                      setPopup({
                        type: "error",
                        message: `Failed to delete API Key: ${errorMsg}`,
                      });
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
          setPopup={setPopup}
          apiKey={selectedApiKey}
        />
      )}
    </>
  );
}

export default function Page() {
  return (
    <>
      <AdminPageTitle title="API Keys" icon={SvgKey} />

      <Main />
    </>
  );
}
