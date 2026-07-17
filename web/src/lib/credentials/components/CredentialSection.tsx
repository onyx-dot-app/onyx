"use client";

import { AccessType, ValidSources } from "@/lib/types";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useState } from "react";
import {
  deleteCredential,
  swapCredential,
  updateCredential,
  updateCredentialWithPrivateKey,
} from "@/lib/credential";
import { toast } from "@opal/layouts";
import { CCPairFullInfo } from "@/app/admin/connector/[ccPairId]/types";
import { Card, Text } from "@opal/components";
import {
  buildCCPairInfoUrl,
  buildSimilarCredentialInfoURL,
} from "@/app/admin/connector/[ccPairId]/lib";
import Modal from "@/refresh-components/Modal";
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
import { isTypedFileField, TypedFile } from "@/lib/connectors/fileTypes";
import { SvgEdit, SvgKey } from "@opal/icons";
import CreateCredential from "@/lib/credentials/components/CreateCredential";
import { CreateStdOAuthCredential } from "@/lib/credentials/components/CreateStdOAuthCredential";
import EditCredential from "@/lib/credentials/components/EditCredential";
import ModifyCredential from "@/lib/credentials/components/ModifyCredential";

export interface CredentialSectionProps {
  ccPair: CCPairFullInfo;
  sourceType: ValidSources;
  refresh: () => void;
}

export default function CredentialSection({
  ccPair,
  sourceType,
  refresh,
}: CredentialSectionProps) {
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
        setShowModifyCredential(false);
        setEditingCredential(null);
        setShowCreateCredential(true);
      } else {
        const redirectUrl = await getConnectorOauthRedirectUrl(sourceType, {});
        if (redirectUrl) {
          window.location.href = redirectUrl;
        }
      }
    } else {
      setShowModifyCredential(false);
      setEditingCredential(null);
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

      toast.success("Swapped credential successfully!");
    } else {
      const errorData = await response.json();
      toast.error(
        `Issue swapping credential: ${
          errorData.detail || errorData.message || "Unknown error"
        }`
      );
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
      toast.success("Updated credential");
      onSucces();
    } else {
      toast.error("Issue updating credential");
    }
  };

  const onEditCredential = (credential: Credential<any>) => {
    setShowModifyCredential(true);
    setShowCreateCredential(false);
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

  const closeCredentialModal = () => {
    setShowModifyCredential(false);
    setShowCreateCredential(false);
    setEditingCredential(null);
  };

  const closeModifyCredential = () => {
    closeCredentialModal();
  };

  const closeCreateCredential = () => {
    setShowCreateCredential(false);
  };

  const closeEditingCredential = () => {
    setEditingCredential(null);
    setShowCreateCredential(false);
    setShowModifyCredential(true);
  };

  const handleCredentialModalOpenChange = (open: boolean) => {
    if (open) {
      setShowModifyCredential(true);
      return;
    }

    if (showCreateCredential) {
      closeCreateCredential();
      return;
    }

    if (editingCredential) {
      closeEditingCredential();
      return;
    }

    closeCredentialModal();
  };

  const showCredentialModal =
    showModifyCredential || editingCredential != null || showCreateCredential;
  const credentialModalTitle = showCreateCredential
    ? `Create ${getSourceDisplayName(sourceType)} Credential`
    : editingCredential
      ? "Edit Credential"
      : "Update Credentials";
  const closeCurrentCredentialView = showCreateCredential
    ? closeCreateCredential
    : editingCredential
      ? closeEditingCredential
      : closeModifyCredential;
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
      <Card padding="lg" border="solid" rounding="lg">
        <div className="flex items-center">
          <div className="shrink-0 mr-3">
            <SvgKey size={16} className="text-muted-foreground" />
          </div>
          <div className="grow flex flex-col justify-center">
            <div className="flex items-center justify-between">
              <div>
                <Text as="p">
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
                <SvgEdit size={16} />
                <span className="sr-only">Update Credentials</span>
              </button>
            </div>
          </div>
        </div>
      </Card>

      {showCredentialModal && (
        <Modal open onOpenChange={handleCredentialModalOpenChange}>
          <Modal.Content>
            <Modal.Header
              icon={showCreateCredential ? SvgKey : SvgEdit}
              title={credentialModalTitle}
              onClose={closeCurrentCredentialView}
            />
            <Modal.Body alignItems="stretch">
              {showCreateCredential ? (
                <>
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
                          onSwap={onSwap}
                          onClose={closeCreateCredential}
                        />
                      )}
                    </>
                  )}
                </>
              ) : editingCredential ? (
                <EditCredential
                  onUpdate={onUpdateCredential}
                  credential={editingCredential}
                  sourceType={sourceType}
                  onClose={closeEditingCredential}
                />
              ) : (
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
              )}
            </Modal.Body>
          </Modal.Content>
        </Modal>
      )}
    </div>
  );
}
