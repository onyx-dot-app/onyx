import React, { useState } from "react";
import { ValidSources } from "@/lib/types";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { FaSwatchbook } from "react-icons/fa";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Modal } from "@/components/Modal";
import { Spinner } from "@/components/Spinner";
import { getSourceDisplayName } from "@/lib/sources";
import { Credential } from "@/lib/connectors/credentials";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { deleteCredential, swapCredential } from "@/lib/credential";
import { useOAuthDetails } from "@/lib/connectors/oauth";
import { CreateStdOAuthCredential } from "./CreateStdOAuthCredential";
import EditCredential from "./EditCredential";
import ModifyCredential from "./ModifyCredential";
import Text from "@/components/ui/text";

interface OutlookCredentialSectionProps {
  ccPair: any; // Replace with proper type
  refresh: () => void;
}

export default function OutlookCredentialSection({
  ccPair,
  refresh,
}: OutlookCredentialSectionProps) {
  const { data: credentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(ValidSources.Outlook),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );

  const { data: editableCredentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(ValidSources.Outlook, true),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );

  const { data: oauthDetails, isLoading: oauthDetailsLoading } =
    useOAuthDetails(ValidSources.Outlook);

  const [showModifyCredential, setShowModifyCredential] = useState(false);
  const [showCreateCredential, setShowCreateCredential] = useState(false);
  const [editingCredential, setEditingCredential] = useState<Credential<any> | null>(
    null
  );

  const { popup, setPopup } = usePopup();

  const onSwap = async (selectedCredential: Credential<any>, connectorId: number) => {
    const response = await swapCredential(selectedCredential.id, connectorId);
    if (response.ok) {
      mutate(buildSimilarCredentialInfoURL(ValidSources.Outlook));
      refresh();
      setPopup({
        message: "Swapped credential successfully!",
        type: "success",
      });
    } else {
      const errorData = await response.json();
      setPopup({
        message: `Issue swapping credential: ${
          errorData.detail || errorData.message || "Unknown error"
        }`,
        type: "error",
      });
    }
  };

  const onDeleteCredential = async (credential: Credential<any>) => {
    const response = await deleteCredential(credential.id, true);
    if (response.ok) {
      mutate(buildSimilarCredentialInfoURL(ValidSources.Outlook));
      refresh();
      setPopup({
        message: "Credential deleted successfully!",
        type: "success",
      });
    } else {
      const errorData = await response.json();
      setPopup({
        message: errorData.message || "Failed to delete credential",
        type: "error",
      });
    }
  };

  const onEditCredential = (credential: Credential<any>) => {
    setShowModifyCredential(false);
    setEditingCredential(credential);
  };

  if (!credentials || !editableCredentials) {
    return <Spinner />;
  }

  return (
    <div className="flex justify-start flex-col gap-y-2">
      {popup}

      <div className="flex gap-x-2">
        <p>Current credential:</p>
        <Text className="ml-1 italic font-bold my-auto">
          {ccPair.credential.name || `Credential #${ccPair.credential.id}`}
        </Text>
      </div>

      <div className="flex text-sm justify-start mr-auto gap-x-2">
        <button
          onClick={() => setShowModifyCredential(true)}
          className="flex items-center gap-x-2 cursor-pointer bg-neutral-800 border-neutral-600 border-2 hover:bg-neutral-700 p-1.5 rounded-lg text-neutral-300"
        >
          <FaSwatchbook />
          Update Credentials
        </button>
      </div>

      {showModifyCredential && (
        <Modal
          onOutsideClick={() => setShowModifyCredential(false)}
          className="max-w-3xl rounded-lg"
          title="Update Outlook Credentials"
        >
          <ModifyCredential
            close={() => setShowModifyCredential(false)}
            source={ValidSources.Outlook}
            attachedConnector={ccPair.connector}
            defaultedCredential={ccPair.credential}
            credentials={credentials}
            editableCredentials={editableCredentials}
            onDeleteCredential={onDeleteCredential}
            onEditCredential={onEditCredential}
            onSwap={onSwap}
            onCreateNew={() => setShowCreateCredential(true)}
          />
        </Modal>
      )}

      {editingCredential && (
        <Modal
          onOutsideClick={() => {
            setEditingCredential(null);
            setShowModifyCredential(true);
          }}
          className="max-w-3xl rounded-lg"
          title="Edit Outlook Credential"
        >
          <EditCredential
            credential={editingCredential}
            onClose={() => {
              setEditingCredential(null);
              setShowModifyCredential(true);
            }}
            setPopup={setPopup}
            onUpdate={async (
              credential: Credential<any>,
              details: Record<string, any>,
              onSuccess: () => void
            ) => {
              // Implement update logic here
              onSuccess();
            }}
          />
        </Modal>
      )}

      {showCreateCredential && (
        <Modal
          onOutsideClick={() => setShowCreateCredential(false)}
          className="max-w-3xl flex flex-col items-start rounded-lg"
          title={`Create ${getSourceDisplayName(ValidSources.Outlook)} Credential`}
        >
          {oauthDetailsLoading ? (
            <Spinner />
          ) : (
            <>
              {oauthDetails && oauthDetails.oauth_enabled ? (
                <CreateStdOAuthCredential
                  sourceType={ValidSources.Outlook}
                  additionalFields={oauthDetails.additional_kwargs}
                />
              ) : (
                <div className="p-4">
                  <p>OAuth is not enabled for Outlook credentials.</p>
                </div>
              )}
            </>
          )}
        </Modal>
      )}
    </div>
  );
} 