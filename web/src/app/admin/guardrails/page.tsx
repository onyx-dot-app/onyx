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

type Validator = {
  id: string;
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
      onClick={() => setShowCreateUpdateForm(true)}
      text={t(k.CREATE_VALIDATOR)}
    />
  );

  if (validators.length === 0) {
    return (
      <div>
        {popup}
        <Text>{t(k.VALIDATORS_TEXT)}</Text>
        {newApiKeyButton}

        {showCreateUpdateForm && (
          <OnyxApiKeyForm
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
      <Text className="mb-4">{t(k.VALIDATORS)}</Text>

      <Table className="overflow-visible">
        <TableHeader>
          <TableRow>
            <TableHead>{t(k.VALIDATOR_NAME_HEADER)}</TableHead>
            <TableHead>{t(k.VALIDATOR_DESCRIPTION_HEADER)}</TableHead>
            <TableHead>{t(k.VALIDATOR_SETTINGS_HEADER)}</TableHead>
            <TableHead>{t(k.VALIDATOR_PERSONAS_HEADER)}</TableHead>
            <TableHead>{t(k.VALIDATOR_GROUPS_HEADER)}</TableHead>
            <TableHead>{t(k.VALIDATOR_ACTIVE_HEADER)}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {validators.map((v) => (
            <TableRow key={v.id}>
              <TableCell className="max-w-64 break-words">{v.name}</TableCell>
              <TableCell className="max-w-96 break-words">
                {v.description || ""}
              </TableCell>
              <TableCell className="max-w-96 break-words text-xs">
                {v.settings ? (
                  <pre className="whitespace-pre-wrap break-words">
                    {JSON.stringify(v.settings, null, 2)}
                  </pre>
                ) : (
                  ""
                )}
              </TableCell>
              <TableCell className="max-w-64 break-words">
                {(v.personas || [])
                  .map((p) => p.name)
                  .filter(Boolean)
                  .join(", ")}
              </TableCell>
              <TableCell className="max-w-64 break-words">
                {(v.groups || [])
                  .map((g) => g.name)
                  .filter(Boolean)
                  .join(", ")}
              </TableCell>
              <TableCell>
                {v.active ? t(k.ACTIVE) : t(k.INACTIVE)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

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
      <AdminPageTitle title={t(k.VALIDATORS_LIST)} icon={<KeyIcon size={32} />}  />
      <Main />
    </div>
  );
}


