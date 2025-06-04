"use client";
import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";

import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { KeyIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import useSWR, { mutate } from "swr";
import { Button } from "@/components/ui/button";
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
import { FiCopy, FiEdit2, FiRefreshCw, FiX } from "react-icons/fi";
import { Modal } from "@/components/Modal";
import { Spinner } from "@/components/Spinner";
import { deleteApiKey, regenerateApiKey } from "./lib";
import { OnyxApiKeyForm } from "./OnyxApiKeyForm";
import { APIKey } from "./types";
import CreateButton from "@/components/ui/createButton";

const API_KEY_TEXT = `Ключи API позволяют получить программный доступ к API SmartSearch. Нажмите кнопку ниже, чтобы сгенерировать новый ключ API.`;

function NewApiKeyModal({
  apiKey,
  onClose,
}: {
  apiKey: string;
  onClose: () => void;
}) {
  const [copyClicked, setCopyClicked] = useState(false);

  return (
    <Modal onOutsideClick={onClose}>
      <div className="px-8 py-8">
        <div className="flex w-full border-b border-border mb-4 pb-4">
          <Title>{i18n.t(k.NEW_API_KEY)}</Title>
        </div>
        <div className="h-32">
          <Text className="mb-4">
            {i18n.t(k.MAKE_SURE_YOU_COPY_YOUR_NEW_AP)}
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
              {i18n.t(k.API_KEY_COPIED)}
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

  const newApiKeyButton = (
    <CreateButton
      onClick={() => setShowCreateUpdateForm(true)}
      text="Создать API-ключ"
    />
  );

  if (apiKeys.length === 0) {
    return (
      <div>
        {popup}
        <Text>{API_KEY_TEXT}</Text>
        {newApiKeyButton}

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

      <Text>{API_KEY_TEXT}</Text>
      {newApiKeyButton}

      <Separator />

      <Title className="mt-6">{i18n.t(k.EXISTING_API_KEYS)}</Title>
      <Table className="overflow-visible">
        <TableHeader>
          <TableRow>
            <TableHead>{i18n.t(k.NAME)}</TableHead>
            <TableHead>{i18n.t(k.API_KEY)}</TableHead>
            <TableHead>{i18n.t(k.ROLE)}</TableHead>
            <TableHead>{i18n.t(k.REGENERATE)}</TableHead>
            <TableHead>{i18n.t(k.DELETE)}</TableHead>
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
                  {apiKey.api_key_name || <i>{i18n.t(k.NULL)}</i>}
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
                        message: `${i18n.t(
                          k.FAILED_TO_REGENERATE_API_KEY
                        )} ${errorMsg}`,
                      });
                      return;
                    }
                    const newKey = (await response.json()) as APIKey;
                    setFullApiKey(newKey.api_key);
                    mutate("/api/admin/api-key");
                  }}
                >
                  <FiRefreshCw className="mr-1 my-auto" />
                  {i18n.t(k.REFRESH)}
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
                        message: `${i18n.t(
                          k.FAILED_TO_DELETE_API_KEY
                        )} ${errorMsg}`,
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
      <AdminPageTitle title="API-ключи" icon={<KeyIcon size={32} />} />

      <Main />
    </div>
  );
}
