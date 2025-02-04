"use client";

import { ValidSources } from "@/lib/types";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { FaSwatchbook } from "react-icons/fa";
import { NewChatIcon } from "@/components/icons/icons";
import { useState } from "react";
import { useUserGroups } from "@/lib/hooks";
import {
  deleteCredential,
  swapCredential,
  updateCredential,
} from "@/lib/credential";
import { usePopup } from "@/components/admin/connectors/Popup";
import CreateCredential from "./actions/CreateCredential";
import { CCPairFullInfo } from "@/app/admin/connector/[ccPairId]/types";
import ModifyCredential from "./actions/ModifyCredential";
import Text from "@/components/ui/text";
import {
  buildCCPairInfoUrl,
  buildSimilarCredentialInfoURL,
} from "@/app/admin/connector/[ccPairId]/lib";
import { Modal } from "../Modal";
import EditCredential from "./actions/EditCredential";
import { getSourceDisplayName } from "@/lib/sources";
import {
  ConfluenceCredentialJson,
  Credential,
} from "@/lib/connectors/credentials";
import {
  getConnectorOauthRedirectUrl,
  useOAuthDetails,
} from "@/lib/connectors/oauth";
import { Spinner } from "@/components/Spinner";
import { CreateStdOAuthCredential } from "@/components/credentials/actions/CreateStdOAuthCredential";

export default function CredentialSection({
  ccPair,
  sourceType,
  refresh,
}: {
  ccPair: CCPairFullInfo;
  sourceType: ValidSources;
  refresh: () => void;
}) {
  const { data: credentials } = useSWR<Credential<ConfluenceCredentialJson>[]>(
    buildSimilarCredentialInfoURL(sourceType),
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );
  const { data: editableCredentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(sourceType, true),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );
  const { data: oauthDetails, isLoading: oauthDetailsLoading } =
    useOAuthDetails(sourceType);

  const makeShowCreateCredential = async () => {
    if (oauthDetailsLoading || !oauthDetails) {
      return;
    }

    if (oauthDetails.oauth_enabled) {
      if (oauthDetails.additional_kwargs.length > 0) {
        setShowCreateCredential(true);
      } else {
        const redirectUrl = await getConnectorOauthRedirectUrl(sourceType, {});
        if (redirectUrl) {
          window.location.href = redirectUrl;
        }
      }
    } else {
      setShowModifyCredential(false);
      setShowCreateCredential(true);
    }
  };

  const onSwap = async (
    selectedCredential: Credential<any>,
    connectorId: number
  ) => {
    await swapCredential(selectedCredential.id, connectorId);
    mutate(buildSimilarCredentialInfoURL(sourceType));
    refresh();

    setPopup({
      message: "Swapped credential succesfully!",
      type: "success",
    });
  };

  const onUpdateCredential = async (
    selectedCredential: Credential<any | null>,
    details: any,
    onSucces: () => void
  ) => {
    const response = await updateCredential(selectedCredential.id, details);
    if (response.ok) {
      setPopup({
        message: "Updated credential",
        type: "success",
      });
      onSucces();
    } else {
      setPopup({
        message: "Issue updating credential",
        type: "error",
      });
    }
  };

  const onEditCredential = (credential: Credential<any>) => {
    closeModifyCredential();
    setEditingCredential(credential);
  };

  const onDeleteCredential = async (credential: Credential<any | null>) => {
    await deleteCredential(credential.id, true);
    mutate(buildCCPairInfoUrl(ccPair.id));
  };
  const defaultedCredential = ccPair.credential;

  const [showModifyCredential, setShowModifyCredential] = useState(false);
  const [showCreateCredential, setShowCreateCredential] = useState(false);
  const [editingCredential, setEditingCredential] =
    useState<Credential<any> | null>(null);

  const closeModifyCredential = () => {
    setShowModifyCredential(false);
  };

  const closeCreateCredential = () => {
    setShowCreateCredential(false);
  };

  const closeEditingCredential = () => {
    setEditingCredential(null);
    setShowModifyCredential(true);
  };
  const { popup, setPopup } = usePopup();

  if (!credentials || !editableCredentials) {
    return <></>;
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
          onClick={() => {
            setShowModifyCredential(true);
          }}
          className="flex items-center gap-x-2 cursor-pointer bg-background-100 border-border border-2 hover:bg-border p-1.5 rounded-lg text-text-700"
        >
          <FaSwatchbook />
          Update Credentials
        </button>
      </div>
      {showModifyCredential && (
        <Modal
          onOutsideClick={closeModifyCredential}
          className="max-w-3xl rounded-lg"
          title="Update Credentials"
        >
          <ModifyCredential
            close={closeModifyCredential}
            source={sourceType}
            attachedConnector={ccPair.connector}
            defaultedCredential={defaultedCredential}
            credentials={credentials}
            editableCredentials={editableCredentials}
            onDeleteCredential={onDeleteCredential}
            onEditCredential={(credential: Credential<any>) =>
              onEditCredential(credential)
            }
            onSwap={onSwap}
            onCreateNew={() => makeShowCreateCredential()}
          />
        </Modal>
      )}

      {editingCredential && (
        <Modal
          onOutsideClick={closeEditingCredential}
          className="max-w-3xl rounded-lg"
          title="Edit Credential"
        >
          <EditCredential
            onUpdate={onUpdateCredential}
            setPopup={setPopup}
            credential={editingCredential}
            onClose={closeEditingCredential}
          />
        </Modal>
      )}

      {showCreateCredential && (
        <Modal
          onOutsideClick={closeCreateCredential}
          className="max-w-3xl rounded-lg"
          title={`Create ${getSourceDisplayName(sourceType)} Credential`}
        >
          {oauthDetailsLoading ? (
            <Spinner />
          ) : (
            <>
              {oauthDetails && oauthDetails.oauth_enabled ? (
                <CreateStdOAuthCredential
                  sourceType={sourceType}
                  additionalFields={oauthDetails.additional_kwargs}
                />
              ) : (
                <CreateCredential
                  sourceType={sourceType}
                  swapConnector={ccPair.connector}
                  setPopup={setPopup}
                  onSwap={onSwap}
                  onClose={closeCreateCredential}
                />
              )}
            </>
          )}
        </Modal>
      )}
    </div>
  );
}
