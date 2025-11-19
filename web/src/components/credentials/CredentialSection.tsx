"use client";

import { AccessType, ValidSources } from "@/lib/types";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { FaKey } from "react-icons/fa";
import { useState } from "react";
import { FiEdit2 } from "react-icons/fi";
import {
  deleteCredential,
  swapCredential,
  updateCredential,
  updateCredentialWithPrivateKey,
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
import { Card } from "../ui/card";
import { isTypedFileField, TypedFile } from "@/lib/connectors/fileTypes";

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
    connectorId: number,
    accessType: AccessType
  ) => {
    const response = await swapCredential(
      selectedCredential.id,
      connectorId,
      accessType
    );
    if (response.ok) {
      mutate(buildSimilarCredentialInfoURL(sourceType));
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

  const onUpdateCredential = async (
    selectedCredential: Credential<any | null>,
    details: any,
    onSucces: () => void
  ) => {
    let privateKey: TypedFile | null = null;
    Object.entries(details).forEach(([key, value]) => {
      if (isTypedFileField(key)) {
        privateKey = value as TypedFile;
        delete details[key];
      }
    });
    let response;
    if (privateKey) {
      response = await updateCredentialWithPrivateKey(
        selectedCredential.id,
        details,
        privateKey
      );
    } else {
      response = await updateCredential(selectedCredential.id, details);
    }
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
    <div
      className="flex
      flex-col
      gap-y-4
      rounded-lg
      bg-background"
    >
      {popup}

      <Card className="p-6">
        <div className="flex items-center">
          <div className="flex-shrink-0 mr-3">
            <FaKey className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="flex-grow flex flex-col justify-center">
            <div className="flex items-center justify-between">
              <div>
                <Text className="font-medium">
                  {ccPair.credential.name ||
                    `Credential #${ccPair.credential.id}`}
                </Text>
                <div className="text-xs text-muted-foreground/70">
                  Created{" "}
                  <i>
                    {new Date(
                      ccPair.credential.time_created
                    ).toLocaleDateString(undefined, {
                      year: "numeric",
                      month: "short",
                      day: "numeric",
                    })}
                  </i>
                  {ccPair.credential.user_email && (
                    <>
                      {" "}
                      by <i>{ccPair.credential.user_email}</i>
                    </>
                  )}
                </div>
              </div>
              <button
                onClick={() => setShowModifyCredential(true)}
                className="inline-flex
                  items-center
                  justify-center
                  p-2
                  rounded-md
                  text-muted-foreground
                  hover:bg-accent
                  hover:text-accent-foreground
                  transition-colors"
              >
                <FiEdit2 className="h-4 w-4" />
                <span className="sr-only">Update Credentials</span>
              </button>
            </div>
          </div>
        </div>
      </Card>

      {showModifyCredential && (
        <Modal
          onOutsideClick={closeModifyCredential}
          className="max-w-3xl rounded-lg"
          title="Update Credentials"
        >
          <ModifyCredential
            close={closeModifyCredential}
            accessType={ccPair.access_type}
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
          className="max-w-3xl flex flex-col items-start rounded-lg"
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
                  accessType={ccPair.access_type}
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
