"use client";

import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { KeyIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import useSWR, { mutate } from "swr";
import { Separator } from "@/components/ui/separator";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Table,
} from "@/components/ui/table";

import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useState } from "react";
import { DeleteButton } from "@/components/DeleteButton";
import { FiCopy, FiEdit2, FiRefreshCw } from "react-icons/fi";
import { Modal } from "@/components/Modal";
import { Spinner } from "@/components/Spinner";
import { deleteApiKey, regenerateApiKey } from "./lib";
import { OnyxApiKeyForm } from "./OnyxApiKeyForm";
import { APIKey } from "./types";
import CreateButton from "@/refresh-components/buttons/CreateButton";

const API_KEY_TEXT = `API Keys allow you to access Onyx APIs programmatically. Click the button below to generate a new API Key.`;

function NewApiKeyModal({
  apiKey,
  onClose,
}: {
  apiKey: string;
  onClose: () => void;
}) {
  const [copyClicked, setCopyClicked] = useState(false);

  return (
    <Modal title="New API Key" onOutsideClick={onClose}>
      <div className="px-8 py-8">
        <div className="h-32">
          <Text className="mb-4">
            Make sure you copy your new API key. You won’t be able to see this
            key again.
          </Text>

          <div className="flex mt-2">
            <b className="my-auto break-all">{apiKey}</b>
            <div
              className="ml-2 my-auto p-2 hover:bg-accent-background-hovered rounded cursor-pointer"
              onClick={() => {
                setCopyClicked(true);
                navigator.clipboard.writeText(apiKey);
                setTimeout(() => {
                  setCopyClicked(false);
                }, 10000);
              }}
            >
              <FiCopy size="16" className="my-auto" />
            </div>
          </div>
          {copyClicked && (
            <Text className="text-success text-xs font-medium mt-1">
              API Key copied!
            </Text>
          )}
        </div>
      </div>
    </Modal>
  );
}

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
    <div className="flex flex-col items-start gap-spacing-paragraph">
      <Text>{API_KEY_TEXT}</Text>
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
    <div>
      {popup}

      {fullApiKey && (
        <NewApiKeyModal
          apiKey={fullApiKey}
          onClose={() => setFullApiKey(null)}
        />
      )}

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
                <div
                  className={`
                  my-auto 
                  flex 
                  mb-1 
                  w-fit 
                  hover:bg-accent-background-hovered cursor-pointer
                  p-2 
                  rounded-lg
                  border-border
                  text-sm`}
                  onClick={() => handleEdit(apiKey)}
                >
                  <FiEdit2 className="my-auto mr-2" />
                  {apiKey.api_key_name || <i>null</i>}
                </div>
              </TableCell>
              <TableCell className="max-w-64">
                {apiKey.api_key_display}
              </TableCell>
              <TableCell className="max-w-64">
                {apiKey.api_key_role.toUpperCase()}
              </TableCell>
              <TableCell>
                <div
                  className={`
                  my-auto 
                  flex 
                  mb-1 
                  w-fit 
                  hover:bg-accent-background-hovered cursor-pointer
                  p-2 
                  rounded-lg
                  border-border
                  text-sm`}
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
                  <FiRefreshCw className="mr-1 my-auto" />
                  Refresh
                </div>
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
    </div>
  );
}

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle title="API Keys" icon={<KeyIcon size={32} />} />

      <Main />
    </div>
  );
}
