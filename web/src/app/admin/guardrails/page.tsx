"use client";
import { useState } from "react";
import { useTranslation } from "@/hooks/useTranslation";
import k from "@/i18n/keys";

import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { KeyIcon } from "@/components/icons/icons";
import { ErrorCallout } from "@/components/ErrorCallout";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";

import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Table,
} from "@/components/ui/table";

import Text from "@/components/ui/text";
import { OnyxApiKeyForm } from "./OnyxApiKeyForm";
import { APIKey } from "./types";
import { usePopup } from "@/components/admin/connectors/Popup";
import CreateButton from "@/components/ui/createButton";
import { Button } from "@/components/ui/button";
import { FiEdit2, FiTrash } from "react-icons/fi";
import { deleteApiKey } from "./lib";

type Validator = {
  config: any;
  id: number;
  owner?: { id?: string; email?: string } | null;
  name: string;
  description?: string | null;
  settings?: Record<string, any> | null;
  personas?: Array<{ id: string; name: string }>; // Assistants
  groups?: Array<{ id: string; name: string }>; // Groups
  active?: boolean;
};

function Main() {
  const { popup, setPopup } = usePopup();
  const { t } = useTranslation();
  const [showCreateUpdateForm, setShowCreateUpdateForm] = useState(false);
  const [selectedApiKey, setSelectedApiKey] = useState<APIKey | undefined>();

  const {
    data: validators,
    isLoading,
    error,
  } = useSWR<Validator[]>("/api/validators", errorHandlingFetcher);

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (!validators || error) {
    return (
      <ErrorCallout
        errorTitle={t(k.FAILED_TO_FETCH_VALIDATORS)}
        errorMsg={error?.info?.detail || error?.toString()}
      />
    );
  }

  const newApiKeyButton = (
    <CreateButton
      onClick={() => {
        setSelectedApiKey(undefined);
        setShowCreateUpdateForm(true);
      }}
      text={t(k.CREATE_VALIDATOR)}
    />
  );

  return (
    <div>
      {popup}
      <div className="mb-4">{newApiKeyButton}</div>
      {validators.length === 0 ? (
        <Text className="mb-4">{t(k.NO_DATA_AVAILABLE)}</Text>
      ) : (
        <Table className="overflow-visible">
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>{t(k.VALIDATOR_NAME_HEADER)}</TableHead>
              <TableHead>{t(k.VALIDATOR_DESCRIPTION_HEADER)}</TableHead>
              <TableHead>{t(k.VALIDATOR_OWNER_HEADER)}</TableHead>
              <TableHead className="w-40">{t(k.ACTIONS)}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {validators.map((v) => (
              <TableRow key={v.id}>
                <TableCell className="max-w-20 break-words">{v.id}</TableCell>
                <TableCell className="max-w-64 break-words">{v.name}</TableCell>
                <TableCell className="max-w-96 break-words">
                  {v.config?.user_description || ""}
                </TableCell>
                <TableCell className="max-w-64 break-words">
                  {v.owner?.email || ""}
                </TableCell>
                <TableCell>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setSelectedApiKey(v as unknown as APIKey);
                        setShowCreateUpdateForm(true);
                      }}
                    >
                      <FiEdit2 className="mr-1" />
                      {t(k.EDIT)}
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={async () => {
                        const response = await deleteApiKey(Number(v.id));
                        if (!response.ok) {
                          const errorMsg = await response.text();
                          setPopup({
                            type: "error",
                            message: `Failed to delete validator ${errorMsg}`,
                          });
                          return;
                        }
                        mutate("/api/validators");
                      }}
                    >
                      <FiTrash className="mr-1" />
                      {t(k.DELETE)}
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {showCreateUpdateForm && (
        <OnyxApiKeyForm
          onClose={() => {
            setShowCreateUpdateForm(false);
            setSelectedApiKey(undefined);
            mutate("/api/validators");
          }}
          setPopup={setPopup}
          apiKey={selectedApiKey}
        />
      )}
    </div>
  );
}

export default function Page() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title={t(k.VALIDATORS_LIST)}
        icon={<KeyIcon size={32} />}
      />
      <Main />
    </div>
  );
}

{
  config: [
    {
      type: "select",
      name: "pii_entities",
      values: ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"],
    },
  ];
}
